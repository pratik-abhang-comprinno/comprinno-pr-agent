#!/usr/bin/env python3
"""
GitHub Action runner for Deep Code Analyzer
Automatically triggered when PRs are opened/updated
"""
import os
import sys
from pathlib import Path

# Add current directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# Change to the script directory
os.chdir(current_dir)

from bedrock.client import BedrockClient
from report.markdown_generator import MarkdownReportGenerator
from github_provider import GitHubProvider
from jira_ticket_extractor import JiraTicketExtractor
from cli import analyze_pr, load_env


def parse_developer_reply(comment_body: str) -> dict:
    """
    Detect if a developer comment indicates they've resolved issues.
    Returns dict with intent and any mentioned issue references.
    """
    if not comment_body:
        return {"intent": None}

    body_lower = comment_body.lower().strip()

    # Skip agent's own comments
    if '🤖' in comment_body or 'Deep Code Analysis' in comment_body:
        return {"intent": None}

    # Detect resolution intent
    resolution_keywords = [
        'resolved', 'fixed', 'done', 'completed', 'addressed',
        'updated', 'corrected', 'handled', 'implemented'
    ]
    for keyword in resolution_keywords:
        if keyword in body_lower:
            return {
                "intent": "resolved",
                "message": comment_body,
                "keyword": keyword
            }

    return {"intent": None}


def get_trigger_comment(github: GitHubProvider) -> dict:
    """Get the comment that triggered this workflow run (if issue_comment event)"""
    trigger_comment_id = os.getenv('GITHUB_COMMENT_ID')
    if not trigger_comment_id:
        return {}
    try:
        comments = github.pr.get_issue_comments()
        for comment in comments:
            if str(comment.id) == trigger_comment_id:
                return {
                    'id': comment.id,
                    'body': comment.body,
                    'author': comment.user.login,
                    'is_bot': comment.user.type == 'Bot' or 'bot' in comment.user.login.lower()
                }
    except Exception:
        pass
    return {}


def get_previous_comments_context(github: GitHubProvider) -> str:
    """Extract all previous agent comments as context string for Bedrock"""
    previous_comments = github.get_previous_agent_comments()
    if not previous_comments:
        return ""

    context = "PREVIOUS REVIEW CONTEXT (all past reviews — do not repeat resolved issues):\n\n"
    total_chars = 0
    for i, comment in enumerate(previous_comments):
        body = comment['body']
        if 'No Issues Found' in body or 'Total Issues | 0' in body:
            continue
        chunk = f"--- Review {i+1} ---\n{body[:1000]}\n\n"
        if total_chars + len(chunk) > 4000:
            break
        context += chunk
        total_chars += len(chunk)

    return context if total_chars > 0 else ""

def main():
    """Run analysis in GitHub Actions environment"""
    
    # Load environment from .env if exists (for local testing only)
    # In GitHub Actions, secrets are already in environment variables
    if os.path.exists('.env'):
        load_env()
    
    # Get PR URL from GitHub Actions environment
    pr_url = os.getenv('GITHUB_PR_URL')
    
    if not pr_url:
        print("❌ Error: GITHUB_PR_URL not set")
        print("   This script should be run in GitHub Actions environment")
        sys.exit(1)
    
    # Check required environment variables
    if not os.getenv('AWS_ACCESS_KEY_ID'):
        print("❌ Error: AWS_ACCESS_KEY_ID not set")
        sys.exit(1)
    
    if not os.getenv('GITHUB_TOKEN'):
        print("❌ Error: GITHUB_TOKEN not set")
        sys.exit(1)
    
    print("🚀 Deep Code Analysis Agent (GitHub Actions)")
    print("=" * 50)
    
    # Initialize components
    try:
        bedrock_client = BedrockClient()
        report_gen = MarkdownReportGenerator()
        print(f"✅ Connected to AWS Bedrock ({os.getenv('AWS_REGION', 'us-east-1')})")
    except Exception as e:
        print(f"❌ Failed to initialize: {e}")
        sys.exit(1)
    
    # Extract Jira ticket from PR branch name or title
    try:
        print("\n" + "="*80)
        print("📋 STEP 1: EXTRACTING JIRA TICKET FROM BRANCH/PR NAME")
        print("="*80)
        
        # Debug: Check if Jira env vars are set
        print(f"\n🔍 DEBUG: Checking environment variables...")
        jira_url = os.getenv('JIRA_URL')
        jira_email = os.getenv('JIRA_EMAIL')
        jira_token = os.getenv('JIRA_API_TOKEN')
        
        print(f"   JIRA_URL: {'✅ SET' if jira_url else '❌ NOT SET'}")
        print(f"   JIRA_EMAIL: {'✅ SET' if jira_email else '❌ NOT SET'}")
        print(f"   JIRA_API_TOKEN: {'✅ SET' if jira_token else '❌ NOT SET'}")
        
        if not (jira_url and jira_email and jira_token):
            print(f"\n⚠️  Missing Jira credentials in environment!")
            print(f"   Please add JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN to GitHub secrets")
            print(f"   Proceeding with standard code analysis...")
        else:
            print(f"\n✅ All Jira credentials found!")
        
        github = GitHubProvider(pr_url)
        pr_info = github.get_pr_info()

        branch_name = pr_info.get('head_branch', '')
        pr_title = pr_info.get('title', '')
        search_text = branch_name if branch_name else pr_title

        print(f"\n🔍 Searching in: {search_text}")

        ticket_info = None
        if search_text:
            extractor = JiraTicketExtractor()
            ticket_id = extractor.extract_ticket_id(search_text)
            if ticket_id:
                ticket_info = extractor.get_ticket_info(ticket_id)
                if ticket_info:
                    print(f"✅ Ticket: [{ticket_info['ticket_id']}] {ticket_info['title']} ({ticket_info['status']})")
                else:
                    print(f"⚠️  Ticket {ticket_id} not found in Jira")
            else:
                print(f"⚠️  No ticket ID found in: {search_text}")

        # Get previous review comments for context
        previous_comments_context = get_previous_comments_context(github)
        if previous_comments_context:
            print("📋 Previous review comments found — passing as context to avoid repetition")

        # Detect if trigger was a developer reply indicating resolution
        developer_reply = {}
        trigger = get_trigger_comment(github)
        if trigger and not trigger.get('is_bot'):
            developer_reply = parse_developer_reply(trigger.get('body', ''))
            if developer_reply.get('intent') == 'resolved':
                print(f"💬 Developer indicated resolution: '{trigger['body'][:80]}' — will prioritize verification")

    except Exception as e:
        print(f"⚠️  Jira integration warning: {e}")
        import traceback
        traceback.print_exc()
        ticket_info = None
        previous_comments_context = ""
        developer_reply = {}
        print(f"   Proceeding with standard code analysis...")

    # Run analysis with Jira + previous comment context
    try:
        analyze_pr(pr_url, bedrock_client, report_gen,
                   jira_context=ticket_info,
                   previous_comments_context=previous_comments_context,
                   developer_reply=developer_reply)

        print("\n" + "="*80)
        print("✨ ANALYSIS COMPLETE")
        print("="*80)
        print("✅ Review comments posted to PR")

    except Exception as e:
        print(f"❌ Analysis failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
