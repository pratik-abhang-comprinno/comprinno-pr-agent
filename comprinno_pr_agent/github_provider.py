import os
from typing import Dict, List, Any
from github import Github, GithubException
import re

class GitHubProvider:
    def __init__(self, pr_url: str):
        self.token = os.getenv('GITHUB_TOKEN')
        if not self.token:
            raise ValueError("GITHUB_TOKEN not set in environment")
        
        self.client = Github(self.token)
        self.pr_url = pr_url
        self.owner, self.repo_name, self.pr_number = self._parse_pr_url(pr_url)
        self.repo = self.client.get_repo(f"{self.owner}/{self.repo_name}")
        self.pr = self.repo.get_pull(self.pr_number)
    
    def _parse_pr_url(self, pr_url: str) -> tuple:
        """Parse GitHub PR URL to extract owner, repo, and PR number"""
        pattern = r'github\.com/([^/]+)/([^/]+)/pull/(\d+)'
        match = re.search(pattern, pr_url)
        if not match:
            raise ValueError(f"Invalid GitHub PR URL: {pr_url}")
        return match.group(1), match.group(2), int(match.group(3))
    
    def get_pr_commits(self) -> List[Dict[str, Any]]:
        """Get all commits in the PR with their messages"""
        commits = []
        for commit in self.pr.get_commits():
            commits.append({
                'sha': commit.sha[:7],
                'message': commit.commit.message,
                'author': commit.commit.author.name,
                'date': commit.commit.author.date.isoformat()
            })
        return commits

    def get_pr_files(self) -> List[Dict[str, Any]]:
        """Get all changed files in the PR with their diffs"""
        files = []
        for file in self.pr.get_files():
            if file.status == 'removed':
                continue
            
            files.append({
                'filename': file.filename,
                'status': file.status,  # 'added', 'modified', 'renamed'
                'patch': file.patch,  # The diff
                'additions': file.additions,
                'deletions': file.deletions,
                'changes': file.changes,
                'blob_url': file.blob_url,
                'raw_url': file.raw_url
            })
        return files
    
    def get_file_content(self, filename: str) -> str:
        """Get the full content of a file from the PR head"""
        try:
            content = self.repo.get_contents(filename, ref=self.pr.head.sha)
            return content.decoded_content.decode('utf-8')
        except GithubException:
            return ""
    
    def parse_diff_lines(self, patch: str) -> List[Dict[str, Any]]:
        """Parse diff patch to extract changed line numbers"""
        if not patch:
            return []
        
        changed_lines = []
        current_line = 0
        
        for line in patch.split('\n'):
            if line.startswith('@@'):
                # Parse hunk header: @@ -old_start,old_count +new_start,new_count @@
                match = re.search(r'\+(\d+)', line)
                if match:
                    current_line = int(match.group(1))
            elif line.startswith('+') and not line.startswith('+++'):
                # This is an added line
                changed_lines.append({
                    'line_number': current_line,
                    'content': line[1:],
                    'type': 'addition'
                })
                current_line += 1
            elif line.startswith('-') and not line.startswith('---'):
                # Deleted line, don't increment
                pass
            elif not line.startswith('\\'):
                # Context line
                current_line += 1
        
        return changed_lines
    
    def post_review_comment(self, filename: str, line_number: int, comment_body: str):
        """Post an inline comment on a specific line in the PR"""
        try:
            self.pr.create_review_comment(
                body=comment_body,
                commit=self.pr.get_commits().reversed[0],
                path=filename,
                line=line_number
            )
            return True
        except GithubException as e:
            print(f"Failed to post comment on {filename}:{line_number} - {e}")
            return False
    
    def post_summary_comment(self, comment_body: str):
        """Post a summary comment on the PR"""
        try:
            self.pr.create_issue_comment(comment_body)
            return True
        except GithubException as e:
            print(f"Failed to post summary comment - {e}")
            return False
    
    def get_pr_info(self) -> Dict[str, Any]:
        """Get basic PR information"""
        return {
            'title': self.pr.title,
            'description': self.pr.body or '',
            'author': self.pr.user.login,
            'base_branch': self.pr.base.ref,
            'head_branch': self.pr.head.ref,
            'state': self.pr.state,
            'number': self.pr.number
        }
    
    def get_previous_agent_comments(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get previous comments from the agent — limited to avoid fetching 100+ comments"""
        agent_comments = []
        for comment in self.pr.get_issue_comments():
            if '🤖 Deep Code Analysis Report' in comment.body or '🤖 Generated by Deep Code Analysis Agent' in comment.body:
                agent_comments.append({
                    'id': comment.id,
                    'body': comment.body,
                    'created_at': comment.created_at,
                    'updated_at': comment.updated_at
                })
                if len(agent_comments) >= limit:
                    break
        return sorted(agent_comments, key=lambda x: x['created_at'], reverse=True)
    
    def check_trigger_comment(self) -> bool:
        """Check if user commented with trigger keyword to re-analyze"""
        trigger_keywords = ['@agent analyze', '@agent re-analyze', '/analyze', 'analyze']
        try:
            # Get latest comments (most recent first)
            comments = list(self.pr.get_issue_comments().reversed)
            if not comments:
                return False
            
            # Check last 5 comments for trigger
            for comment in comments[-5:]:
                # Skip bot comments
                if 'bot' in comment.user.login.lower():
                    continue
                
                for keyword in trigger_keywords:
                    if keyword.lower() in comment.body.lower():
                        print(f"✅ Trigger detected: '{keyword}' in comment by {comment.user.login}")
                        return True
        except Exception as e:
            print(f"⚠️ Error checking trigger: {e}")
        
        return False
    
    def get_pr_commits(self) -> list:
        """Get all commits in the PR"""
        commits = []
        for commit in self.pr.get_commits():
            commits.append({
                'sha': commit.sha[:7],
                'message': commit.commit.message,
                'author': commit.commit.author.name
            })
        return commits

    def get_review_comments(self) -> List[Dict[str, Any]]:
        """Get all review comments (inline comments) from the agent"""
        review_comments = []
        for review in self.pr.get_reviews():
            if review.user.login == 'github-actions[bot]' or '🤖' in (review.body or ''):
                for comment in review.get_comments():
                    review_comments.append({
                        'id': comment.id,
                        'path': comment.path,
                        'line': comment.line,
                        'body': comment.body,
                        'created_at': comment.created_at
                    })
        return review_comments
