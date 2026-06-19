import os
import boto3
import json
from typing import Dict, Any
from datetime import datetime
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from context_manager import PRContextManager

class BedrockClient:
    def __init__(self):
        # Use provided AWS credentials for Bedrock
        self.region = os.getenv('AWS_REGION', 'ap-south-1')
        self.model_id = os.getenv('BEDROCK_MODEL', 'amazon.nova-pro-v1:0')
        self.temperature = 0.3
        self.max_tokens = 4096
        
        session_token = os.getenv('AWS_SESSION_TOKEN')
        self.client = boto3.client(
            service_name='bedrock-runtime',
            region_name=self.region,
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
            **({"aws_session_token": session_token} if session_token else {})
        )
        
        # Context manager will be initialized per PR in analyze_pr
        self.context_manager = None
    
    def analyze_code_with_context(self, code: str, language: str, file_path: str, 
                                pr_number: int, line_number: int = None) -> Dict[str, Any]:
        """Analyze code with conversational context from FAISS"""
        
        # Check for existing conversation at this location
        existing_context = None
        if line_number:
            existing_context = self.context_manager.get_conversation_at_location(
                pr_number, file_path, line_number
            )
        
        # Find similar contexts from previous PRs
        similar_contexts = self.context_manager.find_similar_contexts(code, top_k=3)
        
        # Build context-aware prompt
        context_info = ""
        if existing_context:
            context_info += f"\nPrevious conversation at this location:\n"
            for msg in existing_context['conversation_thread']:
                context_info += f"{msg['author']}: {msg['content']}\n"
        
        if similar_contexts:
            context_info += f"\nSimilar patterns from previous PRs:\n"
            for ctx, score in similar_contexts:
                if score > 0.7:  # High similarity threshold
                    context_info += f"- {ctx['file_path']}: {ctx['conversation_thread'][-1]['content'][:100]}...\n"
        
        # Get analysis with context
        prompt = self._build_context_aware_prompt(code, language, file_path, context_info)
        
        request_body = {
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": {"temperature": self.temperature, "maxTokens": self.max_tokens}
        }
        
        try:
            response = self.client.converse(
                modelId=self.model_id,
                messages=request_body["messages"],
                inferenceConfig=request_body["inferenceConfig"]
            )
            
            result_text = response['output']['message']['content'][0]['text']
            analysis = json.loads(result_text)
            
            # Store this analysis in FAISS for future context
            if line_number and analysis.get('findings'):
                conversation_thread = [{
                    'author': 'comprinno-agent',
                    'content': analysis['findings'][0].get('description', ''),
                    'timestamp': datetime.now().isoformat(),
                    'comment_type': 'initial_finding'
                }]
                
                self.context_manager.add_conversation_context(
                    pr_number, file_path, line_number, code, conversation_thread
                )
            
            return analysis
            
        except Exception as e:
            return {"error": f"Bedrock analysis failed: {str(e)}"}
    
    def _build_context_aware_prompt(self, code: str, language: str, file_path: str, context_info: str) -> str:
        """Build prompt with conversational context"""
        base_prompt = self._build_prompt(code, language, file_path)
        
        if context_info:
            return f"""
CONVERSATIONAL CONTEXT:
{context_info}

Based on the above context:
1. Acknowledge previous discussions if any
2. Avoid repeating resolved issues  
3. Reference similar patterns when relevant
4. Provide contextual responses

{base_prompt}
"""
        return base_prompt
    
    def verify_issue_resolution(self, old_finding: dict, current_code: str, file_path: str) -> Dict[str, Any]:
        """Ask AI to verify if a specific previously flagged issue is resolved in current code"""
        prompt = f"""You are a code reviewer verifying if a previously flagged issue has been resolved.

## Previously Flagged Issue
- Category: {old_finding.get('category')}
- Severity: {old_finding.get('severity')}
- File: {file_path}
- Line: {old_finding.get('line')}
- Description: {old_finding.get('description')}
- Problematic code: {old_finding.get('code_snippet', 'N/A')}

## Current Code
```
{current_code}
```

Analyze whether this specific issue is resolved, still present, or partially fixed.

Return ONLY valid JSON:
{{
  "status": "resolved|still_present|partial",
  "reason": "specific explanation referencing actual code"
}}"""

        try:
            response = self.client.converse(
                modelId=self.model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"temperature": 0.1, "maxTokens": 300}
            )
            result = response['output']['message']['content'][0]['text']
            return self._parse_response(result)
        except Exception as e:
            return {"status": "unknown", "reason": str(e)}

    def find_new_issues(self, code: str, language: str, file_path: str,
                        known_issues: list, ticket_info: dict = None,
                        codebase_context: str = "", all_pr_files: dict = None,
                        coding_standards: str = "", commit_history: str = "") -> Dict[str, Any]:
        """Ask AI to find only NEW issues not already tracked"""
        known_summary = "\n".join(
            f"- [{f.get('category')}] Line {f.get('line')}: {f.get('description', '')[:80]}"
            for f in known_issues
        ) or "None"

        # Include all changed files (YAML, config, etc.) for ticket completion evaluation
        all_files_section = ""
        if all_pr_files:
            other_files = {k: v for k, v in all_pr_files.items() if k != file_path}
            if other_files:
                all_files_section = "## Other Changed Files in This PR (for ticket completion evaluation)\n"
                for fname, content in other_files.items():
                    all_files_section += f"\n### {fname}\n```\n{content}\n```\n"
                all_files_section += "\n"

        ticket_section = ""
        if ticket_info:
            ac = "\n".join(f"  - {c}" for c in ticket_info.get('acceptance_criteria', [])) or "  Not specified"
            ticket_section = f"""## Jira Ticket Context
Ticket: {ticket_info.get('ticket_id')} - {ticket_info.get('title')}
Type: {ticket_info.get('type')} | Priority: {ticket_info.get('priority')} | Status: {ticket_info.get('status')}
Description: {str(ticket_info.get('description', ''))[:500]}
Acceptance Criteria:
{ac}

## Ticket Completion Evaluation Instructions
Evaluate the code against the FULL Jira ticket — title, description, and acceptance criteria together.

For each requirement in the ticket:
1. Understand the GOAL of the requirement, not just its literal wording
2. Look at what the code actually DOES — its behavior and outcome
3. If the code achieves the goal of the requirement, mark it as "done"
4. If the code partially addresses it but something is still missing, mark as "partial" and explain what's missing
5. If the requirement is not addressed at all, mark as "not_done"

Be a pragmatic senior engineer — evaluate intent and outcome, not surface-level keyword matching.

"""

        codebase_section = ""
        if codebase_context:
            codebase_section = f"""## Codebase Context
The following shows how similar patterns are implemented elsewhere in this codebase.
CRITICAL rules:
1. If a pattern appears in the codebase context, do NOT flag it as an issue — it is an established project convention.
2. When suggesting fixes, you MUST follow the EXACT patterns shown here — naming conventions, structure, error handling, imports, logging format.
3. Do NOT apply generic best practices that contradict what this codebase actually does.

{codebase_context}

"""

        standards_section = ""
        if coding_standards:
            standards_section = f"""## Project Coding Standards
The following are the official coding standards for this project. Validate the code against these:

{coding_standards}

"""

        commit_section = ""
        if commit_history:
            commit_section = f"""{commit_history}
"""

        prompt = f"""You are a senior software engineer performing a thorough code review.

Your task has TWO parts:

## PART 1 — Find NEW Issues
Review the code and identify issues that are NOT already in the known issues list.
Do NOT re-report anything already in the known list.
Focus on: security, correctness, performance, reliability, code quality.
Also check for: inconsistency with codebase patterns, duplication of existing code, convention violations.

Additionally check for:
- Deprecated methods or APIs introduced in this PR (only flag NEW changes, not existing code)
- Outdated library usage or version-specific issues introduced in this PR
- Hardcoded credentials, secrets, or sensitive values
- Use of removed or unsupported features in the language/framework version

## PART 2 — Evaluate Jira Ticket Completion
Based on the Jira ticket context provided, evaluate what has been done, what is partially done, and what is still missing.
Consider ALL changed files in this PR (including YAML, config files listed below) — not just the main code file.
Judge by the actual behavior and outcome of the code, not literal keyword matching.

## Already Known Issues (DO NOT re-report these)
{known_summary}

{ticket_section}{codebase_section}{standards_section}{commit_section}{all_files_section}
## Code to Review ({language}) — {file_path}
```{language}
{code}
```

Return ONLY valid JSON:
{{
  "findings": [
    {{
      "category": "string",
      "severity": "Critical|Warning|Info",
      "line_start": <number>,
      "line_end": <number>,
      "description": "string",
      "why_it_matters": "string",
      "how_to_fix": "string",
      "code_example": "string",
      "code_snippet": "string"
    }}
  ],
  "ticket_completion": {{
    "done": ["specific requirement from ticket — how the code satisfies it"],
    "not_done": ["specific requirement from ticket — what is missing"],
    "partial": ["specific requirement from ticket — what was done and what remains"]
  }}
}}
}}"""

        try:
            response = self.client.converse(
                modelId=self.model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"temperature": self.temperature, "maxTokens": self.max_tokens}
            )
            result = response['output']['message']['content'][0]['text']
            return self._parse_response(result)
        except Exception as e:
            print(f"Error calling Bedrock: {e}")
            return {"findings": [], "ticket_completion": {}}

    def analyze_code(self, code: str, language: str, file_path: str, ticket_info: dict = None, previous_findings: list = None, previous_comments_context: str = "") -> Dict[str, Any]:
        """Send code to Bedrock Nova for analysis"""
        
        prompt = self._build_prompt(code, language, file_path, ticket_info, previous_findings, previous_comments_context)
        
        request_body = {
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": prompt}]
                }
            ],
            "inferenceConfig": {
                "temperature": self.temperature,
                "maxTokens": self.max_tokens
            }
        }
        
        try:
            response = self.client.converse(
                modelId=self.model_id,
                messages=request_body["messages"],
                inferenceConfig=request_body["inferenceConfig"]
            )
            
            result_text = response['output']['message']['content'][0]['text']
            return self._parse_response(result_text)
            
        except Exception as e:
            print(f"Error calling Bedrock: {e}")
            return {"error": str(e), "findings": []}
    
    def _build_prompt(self, code: str, language: str, file_path: str, ticket_info: dict = None, previous_findings: list = None, previous_comments_context: str = "") -> str:
        """Build analysis prompt for Bedrock"""
        ticket_section = ""
        if ticket_info:
            ac = "\n".join(f"  - {c}" for c in ticket_info.get('acceptance_criteria', [])) or "  Not specified"
            ticket_section = f"""## JIRA TICKET CONTEXT
Ticket: {ticket_info.get('ticket_id')} - {ticket_info.get('title')}
Type: {ticket_info.get('type')} | Status: {ticket_info.get('status')} | Priority: {ticket_info.get('priority')}
Description: {str(ticket_info.get('description', ''))[:500]}
Acceptance Criteria:
{ac}

Based on the full ticket (title, description, acceptance criteria), analyze the code and determine:
1. What requirements are DONE — and verify the implementation is correct, complete and follows best practices
2. What requirements are NOT YET implemented
3. What requirements are PARTIALLY implemented — explain what's missing

For DONE items: if the implementation has flaws (e.g. insecure fallback, wrong approach), mark as PARTIAL instead.
Be specific — reference actual code lines and variable names in your evaluation.

Return this in the "ticket_completion" field of the JSON response.

"""

        previous_section = ""
        if previous_findings:
            items = []
            for f in previous_findings:
                item = f"  - [{f['category']}] Line {f['line']}: {f['description']}"
                if f.get('code_snippet'):
                    item += f"\n    Problematic code was:\n    ```\n    {f['code_snippet'][:200]}\n    ```"
                items.append(item)
            previous_section = f"""## PREVIOUS REVIEW CONTEXT
The following issues were flagged in previous reviews. Each includes the problematic code that existed at the time:
{chr(10).join(items)}

Instructions:
1. For each issue above, look at the CURRENT CODE and check if the problematic code still exists:
   - If the problematic code is GONE and replaced with a correct fix → add to "resolved_issues" with verification note.
   - If the problematic code STILL EXISTS unchanged → add to "findings".
   - If it was changed but the fix is WRONG → add to "findings" explaining what's wrong.
2. Add any NEW issues found in the current code to "findings".
3. Base your judgment on the ACTUAL CURRENT CODE — not on assumptions from history.

"""

        comments_section = ""
        if previous_comments_context:
            comments_section = f"""## PREVIOUS AGENT COMMENTS
{previous_comments_context}

Do not repeat findings already mentioned above. Focus only on new or unresolved issues.

"""
        return f"""You are an expert code reviewer performing a COMPREHENSIVE, PRODUCTION-READY code analysis of the following {language} code.

{ticket_section}{previous_section}{comments_section}

Analyze ALL aspects across these categories:

## 1. FUNCTIONAL VALIDATION
- Does code satisfy acceptance criteria and business requirements?
- Business logic correctness and completeness
- Edge cases: null/empty values, max limits, invalid formats, boundary conditions
- Backward compatibility - will this break existing functionality?
- Validation rules completeness and correctness
- Error responses consistency and appropriate status codes
- Is the solution overly complex for the requirement?

## 2. ARCHITECTURE & DESIGN
- Architectural guideline violations
- Tight coupling between components
- Layer separation (Controller/Service/Repository/DAO)
- Is logic in the correct layer?
- Single Responsibility Principle violations
- Dependency injection usage
- Design pattern appropriateness

## 3. SCALABILITY & PERFORMANCE
- High load impact (e.g., 10,000 concurrent users)
- Pagination requirements for large datasets
- Caching opportunities and strategy
- Database query optimization (N+1 queries, missing indexes)
- Required database indexes
- Memory leaks or excessive memory usage
- Blocking operations that should be async
- Algorithm time/space complexity

## 4. SECURITY (Specific Checks)
- SQL injection vulnerabilities
- Authentication and authorization checks
- Role-based access control implementation
- Sensitive data exposure in logs or responses
- API overexposure (returning more data than needed)
- Data leakage risks
- Input validation and sanitization
- XSS, CSRF vulnerabilities
- Hardcoded secrets or credentials

## 5. RELIABILITY & ERROR HANDLING
- Graceful failure handling
- Fail-safe mechanisms
- Proper exception handling (not swallowing errors)
- Logging quality - is it useful for debugging?
- Transaction management and rollback
- Retry logic where appropriate
- Circuit breaker patterns for external calls

## 6. TECHNICAL CORRECTNESS
- Async/await pattern correctness
- Blocking calls in async code
- Transaction handling and isolation levels
- Concurrency issues and race conditions
- Thread safety
- Resource cleanup (connections, files, streams)
- Dependency justification - are new dependencies necessary?
- Deprecated API usage
- Type safety and null safety

## 7. CODE QUALITY
- Code structure and organization
- Redundant or unnecessary code
- Naming conventions and clarity
- Code duplication (DRY principle)
- Cyclomatic complexity
- Method/function length
- Class size (god classes)
- Magic numbers and hardcoded values
- Dead code

## 8. TESTING CONSIDERATIONS
- Unit test coverage gaps
- Edge case test scenarios missing
- Integration test needs
- Negative test cases
- Mock usage appropriateness
- Test data quality
- Testability of the code

## 9. IMPACT ASSESSMENT
- Production stability risk level
- Which modules/services are affected?
- Is rollback possible if issues occur?
- Feature toggle requirements
- Database migration requirements
- Deployment considerations

File: {file_path}

Code:
```{language}
{code}
```

For EACH issue found, provide DETAILED, EDUCATIONAL explanations suitable for developers of all experience levels:

Return your analysis as JSON:
{{
  "findings": [
    {{
      "category": "string (e.g., 'SQL Injection Risk', 'Missing Pagination', 'N+1 Query', 'Missing Edge Case', 'Layer Violation', 'Security Risk', 'Scalability Issue', etc.)",
      "severity": "Critical|Warning|Info",
      "line_start": <number>,
      "line_end": <number>,
      "description": "Detailed, educational description of the issue with context",
      "why_it_matters": "Explain the impact, consequences, production risks, and why this is important",
      "how_to_fix": "Step-by-step instructions on how to fix this issue",
      "code_example": "Detailed code example showing the fix with explanatory comments",
      "best_practice": "Related best practice, design principle, or architectural guideline",
      "code_snippet": "The problematic code"
    }}
  ],
  "ticket_completion": {{
    "done": ["requirement — verified correct: explanation of how it's implemented and why it's correct"],
    "not_done": ["requirement — what needs to be implemented"],
    "partial": ["requirement — what was done vs what's still missing"]
  }},
  "resolved_issues": [
    {{
      "category": "previously flagged issue category",
      "description": "what was fixed and verification that the fix is correct"
    }}
  ]
}}

IMPORTANT: Be thorough and check ALL categories. Focus on production-readiness, not just code style.
If no Jira ticket context is provided, return an empty ticket_completion object.

Only return valid JSON, no other text."""
    
    def verify_issue_resolution(self, finding: Dict, current_code: str, file_path: str) -> Dict[str, Any]:
        """Check if a previously flagged issue is fixed, still present, or partially fixed"""
        prompt = f"""You are a code reviewer verifying if a previously flagged issue has been resolved.

Previously flagged issue:
- Category: {finding.get('category')}
- Line: {finding.get('line')}
- Description: {finding.get('description')}
- Code snippet: {finding.get('code_snippet', 'N/A')}

Current code in {file_path}:
```
{current_code[:3000]}
```

Determine if this issue is:
- "resolved": fixed correctly and completely
- "still_present": not fixed at all
- "partial": partially fixed but still has problems

Return JSON only:
{{"status": "resolved|still_present|partial", "reason": "brief explanation"}}"""

        try:
            response = self.client.converse(
                modelId=self.model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"temperature": 0.1, "maxTokens": 256}
            )
            result = response['output']['message']['content'][0]['text']
            return self._parse_response(result)
        except Exception as e:
            return {"status": "unknown", "reason": str(e)}

    def _parse_response(self, response_text: str) -> Dict[str, Any]:
        """Parse Bedrock response"""
        try:
            # Extract JSON from response
            start = response_text.find('{')
            end = response_text.rfind('}') + 1
            if start != -1 and end > start:
                json_str = response_text[start:end]
                return json.loads(json_str)
            return {"findings": []}
        except json.JSONDecodeError:
            return {"findings": [], "error": "Failed to parse response"}
