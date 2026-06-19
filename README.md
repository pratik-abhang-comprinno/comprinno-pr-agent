# 🤖 Comprinno PR Agent — AI Code Review Bot

Automated AI-powered code reviewer that runs on every Pull Request. Posts inline comments with issues, suggested fixes, and validates commit messages.

## Features

- 🔍 AI-powered code analysis (AWS Bedrock Nova)
- 💬 Inline comments on problematic lines
- 📝 Commit message validation (conventional commits)
- 🧠 Issue memory across reviews (FAISS + S3)
- 🎫 Jira ticket integration (optional)
- 🔁 Re-trigger via `@agent analyze` comment

## Supported Languages

| Extension | Language |
|-----------|----------|
| `.py` | Python |
| `.js` | JavaScript |
| `.ts` | TypeScript |
| `.jsx` | React JSX |
| `.tsx` | React TSX |
| `.java` | Java |

## Setup (5 minutes)

### Step 1: Copy files to your repo

Copy these two things into your repository:

```
your-repo/
├── .github/
│   └── workflows/
│       └── code-analysis.yml    ← copy this
├── comprinno_pr_agent/          ← copy this entire folder
│   ├── cli.py
│   ├── github_action_runner.py
│   ├── github_provider.py
│   ├── bedrock/
│   ├── ...
├── (your existing code)
```

### Step 2: Add GitHub Secrets

Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Value | Required |
|--------|-------|----------|
| `AWS_ACCESS_KEY_ID` | AWS access key with Bedrock access | ✅ |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key | ✅ |
| `AWS_REGION` | e.g. `ap-south-1` | ✅ |
| `AWS_SESSION_TOKEN` | Only if using temporary credentials | Optional |
| `JIRA_URL` | e.g. `https://yourorg.atlassian.net` | Optional |
| `JIRA_EMAIL` | Jira account email | Optional |
| `JIRA_API_TOKEN` | Jira API token | Optional |
| `FAISS_S3_BUCKET` | S3 bucket for issue memory | Optional |

> **Note:** `GITHUB_TOKEN` is auto-provided by GitHub Actions — no need to add it.

### Step 3: Done! 🎉

Open any PR → agent will automatically analyze and post comments.

## How It Works

```
PR opened/updated → GitHub Actions triggers → Agent runs:
  1. Fetches PR diff from GitHub API
  2. Extracts Jira ticket from branch name (optional)
  3. Sends code to AWS Bedrock for AI analysis
  4. Posts inline review comments + summary on PR
  5. Stores findings in FAISS for future reference
```

## Triggers

- PR opened, updated (new commits pushed), or reopened
- Comment `@agent analyze` or `/analyze` on the PR

## AWS IAM Permissions Required

The AWS user/role needs:
```json
{
  "Effect": "Allow",
  "Action": ["bedrock:InvokeModel"],
  "Resource": "*"
}
```

Make sure the Bedrock model (`apac.amazon.nova-pro-v1:0`) is enabled in your AWS region.

## Private Repos

Works on private repos out of the box. The `GITHUB_TOKEN` auto-provided by Actions has read/write access to the repo's PRs. No extra setup needed.

## Configuration (Optional)

Create `.pr-agent-config.yml` in your repo root:

```yaml
ignore_patterns:
  - "*.min.js"
  - "package-lock.json"
  - "*.generated.*"
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Action didn't trigger | Ensure `code-analysis.yml` is on `main` branch |
| AWS credentials error | Check secrets are set correctly, no extra spaces |
| Bedrock access denied | Enable model in AWS console + check IAM permissions |
| No comments on PR | File type may not be supported (see supported languages) |
| Jira not detected | Branch name needs ticket ID like `PROJ-123/feature-name` |
