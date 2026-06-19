#!/usr/bin/env python3
import argparse
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Any
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bedrock.client import BedrockClient
from parsers.python_parser import PythonParser
from report.markdown_generator import MarkdownReportGenerator
from github_provider import GitHubProvider
from context_manager import PRContextManager
from jira_ticket_extractor import JiraTicketExtractor
from codebase_context import CodebaseContextProvider
from config_loader import load_config, get_coding_standards, should_ignore_file

def load_env():
    """Load environment variables from .env file"""
    env_file = Path(__file__).parent / '.env'
    load_dotenv(env_file)

def detect_language(file_path: str) -> str:
    """Detect programming language from file extension"""
    ext = file_path.lower().split('.')[-1]
    language_map = {
        'py': 'python',
        'js': 'javascript',
        'java': 'java',
        'ts': 'typescript',
        'jsx': 'javascript',
        'tsx': 'typescript'
    }
    return language_map.get(ext, 'unknown')

def analyze_file(file_path: str, bedrock_client: BedrockClient, report_gen: MarkdownReportGenerator):
    """Analyze a single file"""
    print(f"\n📄 Analyzing: {file_path}")
    
    language = detect_language(file_path)
    if language == 'unknown':
        print(f"⚠️  Unsupported file type: {file_path}")
        return
    
    # Read file
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            code = f.read()
    except Exception as e:
        print(f"❌ Error reading file: {e}")
        return
    
    # Analyze with Bedrock
    print(f"🔍 Running AI analysis...")
    results = bedrock_client.analyze_code(code, language, file_path)
    
    if 'error' in results:
        print(f"❌ Analysis error: {results['error']}")
        return
    
    # Generate report
    print(f"📝 Generating report...")
    report_content = report_gen.generate(file_path, results)
    report_path = report_gen.save_report(file_path, report_content)
    
    findings_count = len(results.get('findings', []))
    print(f"✅ Report saved: {report_path}")
    print(f"   Found {findings_count} issue(s)")

def validate_commit_messages(commits: List[Dict]) -> List[Dict]:
    """Validate commit messages against conventional commit standards"""
    VALID_TYPES = {'feat', 'fix', 'chore', 'docs', 'refactor', 'test', 'style', 'perf', 'ci', 'build', 'revert'}
    VAGUE = {'update', 'fix', 'changes', 'wip', 'misc', 'stuff', 'minor', 'patch', 'temp'}
    CONVENTIONAL = re.compile(r'^(\w+)(\(.+\))?!?:\s.+')

    results = []
    for commit in commits:
        msg = commit['message'].strip().split('\n')[0]  # subject line only
        issues = []

        if CONVENTIONAL.match(msg):
            commit_type = msg.split(':')[0].split('(')[0].lower()
            if commit_type not in VALID_TYPES:
                issues.append(f"Unknown type `{commit_type}` — use one of: {', '.join(sorted(VALID_TYPES))}")
        else:
            issues.append("Missing conventional commit format — use `type: description` (e.g. `fix: resolve SQL injection`)")

        if len(msg) > 72:
            issues.append(f"Subject line too long ({len(msg)} chars) — keep under 72")

        first_word = msg.split(':')[-1].strip().split()[0].lower() if ':' in msg else msg.split()[0].lower()
        if first_word.endswith('ed') or first_word.endswith('ing'):
            issues.append(f"Use imperative mood — `{first_word}` → `{first_word.rstrip('eding')}`")

        if msg.lower().strip().rstrip('.') in VAGUE:
            issues.append("Message is too vague — be specific about what changed")

        results.append({
            'sha': commit['sha'],
            'message': msg,
            'author': commit['author'],
            'status': '✅' if not issues else '❌',
            'issues': issues
        })
    return results


def analyze_pr(pr_url: str, bedrock_client: BedrockClient, report_gen: MarkdownReportGenerator,
               jira_context: dict = None, previous_comments_context: str = "",
               developer_reply: dict = None):
    """Analyze a GitHub PR with FAISS-based issue tracking"""
    print(f"\n🔗 Analyzing GitHub PR: {pr_url}")
    
    try:
        github = GitHubProvider(pr_url)
    except Exception as e:
        print(f"❌ Failed to connect to GitHub: {e}")
        return
    
    pr_info = github.get_pr_info()
    pr_number = pr_info['number']
    print(f"📋 PR #{pr_number}: {pr_info['title']}")
    
    context_mgr = PRContextManager(pr_number)

    # Load agent config from repo root
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    agent_config = load_config(repo_root)
    coding_standards = get_coding_standards(agent_config, repo_root)

    # Initialize codebase context provider (uses Probe if available, falls back to CODING_STANDARDS.md)
    codebase_ctx = CodebaseContextProvider(repo_path=repo_root)

    # Validate commit messages
    commits = github.get_pr_commits()
    commit_validation = validate_commit_messages(commits)
    bad_commits = [c for c in commit_validation if c['status'] == '❌']
    if bad_commits:
        print(f"⚠️  {len(bad_commits)} commit(s) have message issues")
    else:
        print(f"✅ All commit messages follow conventions")
    
    # Extract Jira ticket from PR title
    jira_extractor = JiraTicketExtractor()
    ticket_info = jira_extractor.extract_and_fetch(pr_info['title'])
    if ticket_info:
        print(f"🎫 Linked ticket: {ticket_info['ticket_id']} - {ticket_info['title']}")
    else:
        print(f"⚠️  No Jira ticket found in PR title")

    # Fetch previous agent comments (for display/context only — not for parsing findings)
    previous_comments = github.get_previous_agent_comments()
    if previous_comments:
        print(f"📋 Previous review comments found — passing as context")

    # Full analysis
    pr_files = github.get_pr_files()
    print(f"\n📁 Found {len(pr_files)} changed file(s)")

    all_findings = []
    ticket_completion = {"done": [], "not_done": [], "partial": []}
    all_resolved_issues = []
    verified_previous = []

    # Get all current file contents
    file_contents = {}
    for file_info in pr_files:
        filename = file_info['filename']
        if detect_language(filename) != 'unknown':
            code = github.get_file_content(filename)
            if code:
                file_contents[filename] = code

    # Load previous findings from FAISS (single source of truth)
    previous_findings = []
    faiss_open = context_mgr.get_open_issues()
    if faiss_open:
        print(f"📦 Loaded {len(faiss_open)} open issue(s) from FAISS")
        for issue in faiss_open:
            category = issue.get('category', '')
            if not category or len(category) > 50 or '\n' in category:
                continue
            previous_findings.append({
                'id': issue['id'],
                'category': category,
                'line': str(issue.get('line', 0)),
                'description': issue.get('description', '')[:200],
                'code_snippet': issue.get('code_snippet', '')[:300],
                'from_pr': issue.get('pr_number')
            })
        print(f"📋 Found {len(previous_findings)} previously flagged issue(s) — will check if resolved")
    else:
        print(f"🆕 No previous analysis found — running fresh review")

    # Get cross-PR open issues from FAISS (issues from other PRs on same files)
    changed_files = [fi['filename'] for fi in pr_files if detect_language(fi['filename']) != 'unknown']
    cross_pr_issues = context_mgr.get_cross_pr_open_issues(changed_files)
    if cross_pr_issues:
        print(f"\n🔗 Found {len(cross_pr_issues)} open issue(s) from previous PRs on same files")
        for issue in cross_pr_issues:
            category = issue.get('category', '')
            # Skip corrupted FAISS entries — valid categories are short strings
            if not category or len(category) > 50 or '\n' in category or '**' in category:
                continue
            key = f"{category}:{issue.get('line')}"
            if not any(f.get('category') == category and f.get('line') == str(issue.get('line')) for f in previous_findings):
                previous_findings.append({
                    'category': category,
                    'line': str(issue['line']),
                    'description': issue['description'][:200],
                    'code_snippet': issue.get('code_snippet', ''),
                    'from_pr': issue.get('pr_number')
                })

    # Step 1 — Verify each previous finding with focused AI call
    if previous_findings:
        if developer_reply and developer_reply.get('intent') == 'resolved':
            print(f"\n💬 Developer indicated resolution — verifying all previous issues...")
        else:
            print(f"\n🔎 Verifying {len(previous_findings)} previous issue(s)...")
        all_current_code = "\n\n".join(
            f"# {fname}\n{code}" for fname, code in file_contents.items()
        )
        for old_finding in previous_findings:
            print(f"   Checking: [{old_finding['category']}] Line {old_finding['line']}...")
            result = bedrock_client.verify_issue_resolution(old_finding, all_current_code, "PR files")
            status = result.get('status', 'unknown')
            reason = result.get('reason', '')
            verified_previous.append({
                'category': old_finding['category'],
                'line': old_finding['line'],
                'description': old_finding['description'],
                'status': status,
                'reason': reason,
                'from_pr': old_finding.get('from_pr')
            })
            print(f"   → {status}: {reason[:60]}")
            # Update FAISS status if resolved
            if status == 'resolved' and old_finding.get('id') is not None:
                context_mgr.mark_resolved(old_finding['id'], old_finding.get('from_pr'))

    # Step 2 — Find NEW issues per file (excluding known ones)
    # Include ALL FAISS findings (open + fixed) so Bedrock never re-reports them
    all_faiss_findings = context_mgr.metadata  # all findings ever stored for this PR
    known_issues = previous_findings + [
        {'category': m['category'], 'line': str(m['line']), 'description': m['description']}
        for m in all_faiss_findings
        if f"{m['category']}:{m['line']}" not in {f"{f['category']}:{f['line']}" for f in previous_findings}
    ]

    # Collect all changed file contents including non-code files (YAML, JSON, config)
    # for ticket completion evaluation
    all_changed_contents = {}
    for file_info in pr_files:
        fname = file_info['filename']
        if file_info.get('status') != 'removed':
            content = github.get_file_content(fname)
            if content:
                all_changed_contents[fname] = content[:1000]  # cap per file

    for file_info in pr_files:
        filename = file_info['filename']
        language = detect_language(filename)
        if language == 'unknown':
            continue

        # Skip files matching ignore patterns from config
        if should_ignore_file(filename, agent_config):
            print(f"⏭️  Skipping {filename} (matches ignore pattern)")
            continue

        code = file_contents.get(filename)
        if not code:
            continue

        changed_lines = github.parse_diff_lines(file_info['patch'])
        if not changed_lines:
            continue

        print(f"📄 Finding new issues: {filename}")
        codebase_context = codebase_ctx.get_context_for_file(filename, code, language)
        if codebase_context:
            print(f"🔍 Codebase context loaded for {filename}")
        # Build commit history summary for Bedrock context
        commit_history_summary = ""
        if commits:
            commit_history_summary = "## Commit History in This PR\n"
            for c in commits:
                commit_history_summary += f"- `{c['sha']}` {c['message'].split(chr(10))[0][:80]} ({c['author']})\n"
            commit_history_summary += "\nUse this to understand how the code evolved. Focus on the latest changes.\n"

        results = bedrock_client.find_new_issues(
            code, language, filename,
            known_issues=known_issues,
            ticket_info=jira_context or ticket_info,
            codebase_context=codebase_context,
            all_pr_files=all_changed_contents,
            coding_standards=coding_standards,
            commit_history=commit_history_summary
        )

        if 'error' in results:
            continue

        # Collect ticket completion
        tc = results.get('ticket_completion', {})
        for key in ['done', 'not_done', 'partial']:
            ticket_completion[key].extend(tc.get(key, []))

        findings = results.get('findings', [])
        changed_line_numbers = {cl['line_number'] for cl in changed_lines}
        is_new_file = file_info.get('status') == 'added' or len(changed_line_numbers) == len(code.splitlines())
        relevant_findings = findings if is_new_file else [
            f for f in findings
            if any(f.get('line_start', 0) <= ln <= f.get('line_end', 0) for ln in changed_line_numbers)
        ]

        # Validate code_snippet exists in current file — discard false positives
        # where Bedrock flags code that was already fixed or doesn't exist
        validated_findings = []
        for f in relevant_findings:
            snippet = f.get('code_snippet', '').strip()
            if snippet and len(snippet) > 5:
                # Normalize whitespace for comparison
                normalized_snippet = ' '.join(snippet.split())
                normalized_code = ' '.join(code.split())
                if normalized_snippet not in normalized_code:
                    continue  # code no longer exists — false positive, skip
            validated_findings.append(f)
        relevant_findings = validated_findings

        for f in relevant_findings:
            f['file'] = filename

        # Post inline comments
        # Build a map of line_number → content from the diff
        diff_line_map = {cl['line_number']: cl['content'] for cl in changed_lines}

        for finding in relevant_findings:
            line = finding.get('line_start')
            if not line:
                continue
            if line not in changed_line_numbers and not is_new_file:
                continue
            severity_emoji = {'Critical': '🔴', 'Warning': '🟡', 'Info': '🔵'}.get(finding.get('severity'), '⚪')

            # Get the actual changed lines around the finding
            changed_code_section = ""
            flagged_lines = [
                diff_line_map[ln]
                for ln in range(finding.get('line_start', line), finding.get('line_end', line) + 1)
                if ln in diff_line_map
            ]
            if flagged_lines:
                changed_code_section = f"\n\n**Changed code (flagged):**\n```python\n" + "\n".join(flagged_lines) + "\n```"

            inline_body = (
                f"{severity_emoji} **{finding.get('category')}** ({finding.get('severity')}) — 🆕 NEW\n\n"
                f"{finding.get('description', '')}"
                f"{changed_code_section}\n\n"
                f"**Why it matters:** {finding.get('why_it_matters', '')}\n\n"
                f"**How to fix:** {finding.get('how_to_fix', '')}"
            )
            if finding.get('code_example'):
                inline_body += f"\n\n**Suggested fix:**\n```python\n{finding.get('code_example')}\n```"
            github.post_review_comment(filename, line, inline_body)

        all_findings.extend(relevant_findings)
    
    # Store findings in FAISS
    if all_findings:
        context_mgr.store_findings(all_findings)
        print(f"💾 Stored {len(all_findings)} findings in FAISS")
    
    # Post consolidated comment
    print(f"\n📝 Generating report...")
    summary = generate_pr_summary(pr_info, pr_files, all_findings, previous_comments, ticket_info=ticket_info, previous_findings=previous_findings, ticket_completion=ticket_completion, resolved_issues=all_resolved_issues, commit_validation=commit_validation, verified_previous=verified_previous, developer_reply=developer_reply)
    github.post_summary_comment(summary)
    
    print(f"\n✅ Analysis complete! Found {len(all_findings)} issue(s)")



def parse_previous_findings(comments: list) -> list:
    """Extract open issues from ALL agent comments — only numbered findings, skip resolved ones"""
    if not comments:
        return []

    import re

    # First — collect all resolved keys from ALL comments
    resolved_keys = set()
    for comment in comments:
        for match in re.finditer(r'[-•]\s+\*\*(.+?)\*\*\s+\(Line\s+(\w+)\)[^—\n]*—[^—\n]*✅', comment['body']):
            resolved_keys.add(f"{match.group(1).strip()}:{match.group(2).strip()}")

    # Second — collect ONLY numbered findings (1. 2. 3.) from Issues Found sections
    seen = set()
    findings = []

    for comment in comments:
        body = comment['body']
        issues_idx = body.find('### Issues Found')
        if issues_idx == -1:
            continue
        section = body[issues_idx:]

        # Only match numbered list items — not bullet points
        for match in re.finditer(
            r'^\d+\.\s+\*\*(.+?)\*\*\s+\(Line\s+(\w+)\)\s*\n+\s*\*\*Issue:\*\*\s+(.+?)$',
            section, re.MULTILINE
        ):
            category = match.group(1).strip()
            line = match.group(2).strip()
            key = f"{category}:{line}"

            if key in seen or key in resolved_keys:
                continue
            seen.add(key)

            desc_end = match.end()
            snippet_match = re.search(r'\*\*Problematic code:\*\*\s*```\w*\n\s*(.*?)```', section[desc_end:desc_end+1000], re.DOTALL)
            snippet = snippet_match.group(1).strip() if snippet_match else ''

            findings.append({
                'id': len(findings),
                'category': category,
                'line': line,
                'description': match.group(3).strip()[:200],
                'code_snippet': snippet[:300]
            })

    return findings



    """Generate report comparing fixed vs still-present issues"""
    summary = f"## 🤖 Issue Resolution Check\n\n"
    summary += f"**PR:** #{pr_info['number']}\n\n"
    
    if fixed_issues:
        summary += f"### ✅ Fixed Issues ({len(fixed_issues)})\n\n"
        for issue in fixed_issues[:10]:
            summary += f"- **{issue.get('category', 'Issue')}** (Line {issue.get('line', '?')})\n"
            summary += f"  {issue.get('description', '')[:80]}...\n\n"
    
    if still_present:
        summary += f"### ❌ Still Present ({len(still_present)})\n\n"
        for issue in still_present[:10]:
            summary += f"- **{issue.get('category', 'Issue')}** (Line {issue.get('line', '?')})\n"
            summary += f"  {issue.get('description', '')[:80]}...\n\n"
    
    if not fixed_issues and not still_present:
        summary += f"### ℹ️ No previous issues to compare\n\n"
    
    summary += f"---\n*🤖 Generated by Deep Code Analysis Agent*"
    return summary


def generate_pr_summary(pr_info: dict, files: List, findings: List, previous_comments: List = None, ticket_info: dict = None, previous_findings: list = None, ticket_completion: dict = None, resolved_issues: list = None, commit_validation: list = None, verified_previous: list = None, developer_reply: dict = None) -> str:
    """Generate consolidated PR summary comment with ticket details"""
    critical = sum(1 for f in findings if f.get('severity') == 'Critical')
    warning = sum(1 for f in findings if f.get('severity') == 'Warning')
    info = sum(1 for f in findings if f.get('severity') == 'Info')

    summary = f"## 🤖 Deep Code Analysis Report\n\n"
    summary += f"**PR:** #{pr_info['number']} - {pr_info['title']}\n\n"

    # Show developer reply context if present
    if developer_reply and developer_reply.get('intent') == 'resolved':
        summary += f"> 💬 **Developer indicated:** \"{developer_reply.get('message', '')[:100]}\" — verification results below\n\n"

    # Verified previous issues
    if verified_previous:
        resolved = [v for v in verified_previous if v['status'] == 'resolved']
        still_present = [v for v in verified_previous if v['status'] == 'still_present']
        partial = [v for v in verified_previous if v['status'] == 'partial']

        summary += f"### 🔁 Previous Issues — Verification\n\n"
        if resolved:
            summary += f"**✅ Resolved ({len(resolved)}):**\n"
            for v in resolved:
                from_pr = f" *(from PR #{v['from_pr']})*" if v.get('from_pr') and v['from_pr'] != pr_info['number'] else ""
                summary += f"- **{v['category']}** (Line {v['line']}){from_pr} — {v['reason'][:100]}\n"
            summary += "\n"
        if still_present:
            summary += f"**❌ Still Present ({len(still_present)}):**\n"
            for v in still_present:
                from_pr = f" *(from PR #{v['from_pr']})*" if v.get('from_pr') and v['from_pr'] != pr_info['number'] else ""
                summary += f"- **{v['category']}** (Line {v['line']}){from_pr} — {v['reason'][:100]}\n"
            summary += "\n"
        if partial:
            summary += f"**⚠️ Partial ({len(partial)}):**\n"
            for v in partial:
                from_pr = f" *(from PR #{v['from_pr']})*" if v.get('from_pr') and v['from_pr'] != pr_info['number'] else ""
                summary += f"- **{v['category']}** (Line {v['line']}){from_pr} — {v['reason'][:100]}\n"
            summary += "\n"

    # Add Ticket Details
    if ticket_info:
        summary += f"---\n\n"
        summary += f"### 📋 Jira Ticket Details\n\n"
        summary += f"**Ticket:** {ticket_info['ticket_id']} - {ticket_info['title']}\n"
        summary += f"**Type:** {ticket_info['type']} | **Status:** {ticket_info['status']} | **Priority:** {ticket_info['priority']}\n"
        summary += f"**Assignee:** {ticket_info['assignee']}\n\n"
        summary += f"**Description:** {str(ticket_info['description'])[:150]}...\n\n"
    
    # Show if this is a re-analysis
    if previous_comments:
        summary += f"**Status:** Re-analysis (Previous analysis: {len(previous_comments)} comment(s))\n\n"
    
    summary += f"### 🔍 Code Analysis Results\n\n"
    summary += f"| Metric | Count |\n"
    summary += f"|--------|-------|\n"
    summary += f"| Files Analyzed | {len(files)} |\n"
    summary += f"| Total Issues | {len(findings)} |\n"
    summary += f"| 🔴 Critical | {critical} |\n"
    summary += f"| 🟡 Warning | {warning} |\n"
    summary += f"| 🔵 Info | {info} |\n\n"

    # Commit message validation
    if commit_validation:
        summary += f"### 📝 Commit Message Review\n\n"
        summary += f"| Commit | Message | Status |\n"
        summary += f"|--------|---------|--------|\n"
        for c in commit_validation:
            summary += f"| `{c['sha']}` | {c['message'][:60]} | {c['status']} |\n"
        summary += "\n"
        bad = [c for c in commit_validation if c['issues']]
        if bad:
            summary += f"**Issues:**\n"
            for c in bad:
                for issue in c['issues']:
                    summary += f"- `{c['sha']}`: {issue}\n"
            summary += "\n"
    
    if ticket_info:
        summary += f"### ✅ Ticket Validation\n\n"
        summary += f"- ✅ Analyzed code against ticket: {ticket_info['ticket_id']}\n"
        summary += f"- ✅ Checked {len(files)} changed files\n"
        summary += f"- ✅ Validated code quality and best practices\n"
        summary += f"- ✅ Found {len(findings)} issue(s)\n\n"

        # Ticket completion status
        if ticket_completion and any(ticket_completion.values()):
            summary += f"### 📋 Jira Ticket Completion — {ticket_info['ticket_id']}\n\n"
            summary += f"**Ticket:** {ticket_info['title']}\n\n"

            def format_tc_item(item):
                """Normalize ticket completion item — handle both string and dict formats"""
                if isinstance(item, dict):
                    req = item.get('requirement', item.get('done', ''))
                    missing = item.get('missing', item.get('not_done', ''))
                    return f"{req}" + (f" — missing: {missing}" if missing else "")
                return str(item)

            if ticket_completion.get('done'):
                summary += f"**✅ Done:**\n"
                for item in ticket_completion['done']:
                    summary += f"- {format_tc_item(item)}\n"
                summary += "\n"
            if ticket_completion.get('partial'):
                summary += f"**⚠️ Partially Done:**\n"
                for item in ticket_completion['partial']:
                    summary += f"- {format_tc_item(item)}\n"
                summary += "\n"
            if ticket_completion.get('not_done'):
                summary += f"**❌ Not Yet Done:**\n"
                for item in ticket_completion['not_done']:
                    summary += f"- {format_tc_item(item)}\n"
                summary += "\n"

    # Resolved issues from previous review — deduplicated by category
    if resolved_issues:
        seen = set()
        unique_resolved = []
        for issue in resolved_issues:
            key = issue.get('category', '')
            if key not in seen:
                seen.add(key)
                unique_resolved.append(issue)
        summary += f"### ✅ Resolved Since Last Review\n\n"
        for issue in unique_resolved:
            summary += f"- **{issue.get('category')}** — {issue.get('description')}\n"
        summary += "\n"
    if findings:
        summary += f"### Issues Found\n\n"
        
        # Group by severity
        for severity in ['Critical', 'Warning', 'Info']:
            severity_findings = [f for f in findings if f.get('severity') == severity]
            if severity_findings:
                emoji = {'Critical': '🔴', 'Warning': '🟡', 'Info': '🔵'}.get(severity, '⚪')
                summary += f"#### {emoji} {severity} ({len(severity_findings)})\n\n"
                
                for i, finding in enumerate(severity_findings[:5], 1):  # Limit to 5 per severity
                    summary += f"{i}. **{finding.get('category', 'Issue')}** (Line {finding.get('line_start', '?')})\n\n"
                    summary += f"   **Issue:** {finding.get('description', 'No description')}\n\n"
                    if finding.get('why_it_matters'):
                        summary += f"   **Why it matters:** {finding.get('why_it_matters')}\n\n"
                    if finding.get('how_to_fix'):
                        summary += f"   **How to fix:** {finding.get('how_to_fix')}\n\n"
                    if finding.get('code_snippet'):
                        summary += f"   **Problematic code:**\n   ```python\n   {finding.get('code_snippet')}\n   ```\n\n"
                    if finding.get('code_example'):
                        summary += f"   **Suggested fix:**\n   ```python\n   {finding.get('code_example')}\n   ```\n\n"
                
                if len(severity_findings) > 5:
                    summary += f"   ... and {len(severity_findings) - 5} more\n\n"
        
        summary += f"### Recommendations\n\n"
        summary += f"1. ⚠️ Address **Critical** issues before merging\n"
        summary += f"2. 📋 Review **Warning** issues and plan fixes\n"
        summary += f"3. 💡 Consider **Info** items for code quality\n\n"
        summary += f"**To re-analyze:** Comment `@agent analyze` on this PR\n\n"
    else:
        summary += f"### ✅ No Issues Found!\n\n"
        summary += f"The changed code looks good. Great work! 🎉\n\n"
    
    summary += f"---\n*Powered by AWS Bedrock Nova | [Deep Code Analyzer](https://github.com)*"
    return summary

def analyze_directory(dir_path: str, bedrock_client: BedrockClient, report_gen: MarkdownReportGenerator):
    """Analyze all supported files in directory and generate consolidated report"""
    supported_extensions = ['.py', '.js', '.java', '.ts', '.jsx', '.tsx']
    
    files = []
    for root, _, filenames in os.walk(dir_path):
        for filename in filenames:
            if any(filename.endswith(ext) for ext in supported_extensions):
                files.append(os.path.join(root, filename))
    
    if not files:
        print(f"⚠️  No supported files found in {dir_path}")
        return
    
    print(f"\n📁 Found {len(files)} file(s) to analyze")
    
    # Reset consolidated data
    report_gen.reset()
    
    # Analyze each file and collect results
    for file_path in files:
        print(f"\n📄 Analyzing: {file_path}")
        
        language = detect_language(file_path)
        if language == 'unknown':
            print(f"⚠️  Unsupported file type: {file_path}")
            continue
        
        # Read file
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                code = f.read()
        except Exception as e:
            print(f"❌ Error reading file: {e}")
            continue
        
        # Analyze with Bedrock
        print(f"🔍 Running comprehensive AI analysis...")
        results = bedrock_client.analyze_code(code, language, file_path)
        
        if 'error' in results:
            print(f"❌ Analysis error: {results['error']}")
            continue
        
        # Add to consolidated report
        report_gen.add_file_analysis(file_path, results)
        
        findings_count = len(results.get('findings', []))
        print(f"✅ Analysis complete: {findings_count} finding(s)")
    
    # Generate and save consolidated report
    print(f"\n📝 Generating consolidated report...")
    dir_name = os.path.basename(os.path.normpath(dir_path))
    report_content = report_gen.generate_consolidated_report(dir_name)
    report_path = report_gen.save_consolidated_report(dir_path, report_content)
    
    print(f"✅ Consolidated report saved: {report_path}")

def main():
    parser = argparse.ArgumentParser(
        description='Deep Code Analysis Agent - Automated code quality analyzer',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze a single file
  python cli.py --file sample.py
  
  # Analyze all files in a directory
  python cli.py --directory ./src
  
  # Analyze a GitHub PR
  python cli.py --pr_url https://github.com/owner/repo/pull/123
  
  # Analyze with custom AWS region
  AWS_REGION=us-west-2 python cli.py --file app.py
        """
    )
    
    parser.add_argument('--file', type=str, help='Path to a single file to analyze')
    parser.add_argument('--directory', type=str, help='Path to directory to analyze')
    parser.add_argument('--pr_url', type=str, help='GitHub PR URL to analyze')
    parser.add_argument('--version', action='version', version='Deep Code Analyzer v1.0.0')
    
    args = parser.parse_args()
    
    if not args.file and not args.directory and not args.pr_url:
        parser.print_help()
        sys.exit(1)
    
    # Load environment
    load_env()
    
    # Check AWS credentials
    if not os.getenv('AWS_ACCESS_KEY_ID'):
        print("❌ Error: AWS_ACCESS_KEY_ID not set")
        print("   Please configure .env file or set environment variables")
        sys.exit(1)
    
    # Check GitHub token if analyzing PR
    if args.pr_url and not os.getenv('GITHUB_TOKEN'):
        print("❌ Error: GITHUB_TOKEN not set")
        print("   Please configure .env file or set GITHUB_TOKEN environment variable")
        sys.exit(1)
    
    print("🚀 Deep Code Analysis Agent")
    print("=" * 50)
    
    # Initialize components
    try:
        bedrock_client = BedrockClient()
        report_gen = MarkdownReportGenerator()
        print(f"✅ Connected to AWS Bedrock ({os.getenv('AWS_REGION', 'us-east-1')})")
    except Exception as e:
        print(f"❌ Failed to initialize: {e}")
        sys.exit(1)
    
    # Run analysis
    if args.pr_url:
        analyze_pr(args.pr_url, bedrock_client, report_gen)
    elif args.file:
        if not os.path.exists(args.file):
            print(f"❌ File not found: {args.file}")
            sys.exit(1)
        analyze_file(args.file, bedrock_client, report_gen)
    elif args.directory:
        if not os.path.isdir(args.directory):
            print(f"❌ Directory not found: {args.directory}")
            sys.exit(1)
        analyze_directory(args.directory, bedrock_client, report_gen)
    
    print("\n✨ Analysis complete!")

if __name__ == '__main__':
    main()
