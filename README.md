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

---

## Setup Options

Choose one of the two approaches:

---

### Option A: Standalone Workflow (Recommended — Zero Copy)

Teams only need to add **1 file** to their repo. The agent code is cloned at runtime from this central repo.

#### Steps:

1. Copy `workflow-standalone.yml` to your repo as `.github/workflows/code-analysis.yml`

2. Add these secrets to your repo (Settings → Secrets → Actions):

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

3. Done! Open a PR — agent runs automatically.

> **Note:** Secret names can only contain alphanumeric characters ([a-z], [A-Z], [0-9]) or underscores (_). Spaces are not allowed. Must start with a letter ([a-z], [A-Z]) or underscores (_). Paste values without quotes or extra spaces.

#### Pros:
- ✅ One file to copy
- ✅ Agent updates automatically (always uses latest from this repo)
- ✅ No code duplication
- ✅ No PAT needed (repo is public)

---

### Option B: Git Submodule

Link the agent code as a submodule in your repo.

#### Steps:

1. Add submodule:
```bash
git submodule add https://github.com/pratik-abhang-comprinno/comprinno-pr-agent.git comprinno_pr_agent_repo
```

2. Copy the workflow file:
```bash
mkdir -p .github/workflows
cp comprinno_pr_agent_repo/.github/workflows/code-analysis.yml .github/workflows/
```

3. Update your workflow's `working-directory` to point to the submodule:
```yaml
working-directory: comprinno_pr_agent_repo/comprinno_pr_agent
```

4. Add workflow step to init submodules:
```yaml
- name: Checkout repository
  uses: actions/checkout@v4
  with:
    fetch-depth: 0
    ref: main
    submodules: true
```

5. Add secrets (same as Option A)

6. Commit and push:
```bash
git add .
git commit -m "chore: add PR agent submodule"
git push
```

#### To update agent later:
```bash
git submodule update --remote
git add comprinno_pr_agent_repo
git commit -m "chore: update PR agent"
git push
```

#### Pros:
- ✅ Version pinned — you control when to update
- ✅ Code visible in your repo

---

### Option C: Direct Copy (Simplest)

Copy the agent code directly into your repo.

#### Steps:

1. Copy `comprinno_pr_agent/` folder to your repo root
2. Copy `.github/workflows/code-analysis.yml` to your repo
3. Add secrets (AWS keys only — no `GH_PAT` needed)
4. Push to main

#### Pros:
- ✅ No PAT needed
- ✅ Works immediately

#### Cons:
- ❌ Manual updates — need to re-copy when agent is updated

---

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

## Private Repos

Works on private repos out of the box:
- `GITHUB_TOKEN` (auto-provided by Actions) has access to the repo's PRs
- The agent source repo is public — no extra token needed to clone it

## AWS IAM Setup (Step-by-Step)

### Step 1: Create IAM User

1. Go to: https://console.aws.amazon.com/iam/home#/users
2. Click **"Create user"**
3. User name: `pr-agent-bot`
4. ❌ Don't check "Provide user access to the AWS Management Console"
5. Click **Next**

### Step 2: Create & Attach Policy (Bedrock — Required)

1. On the permissions page, click **"Attach policies directly"**
2. Click **"Create policy"** (opens new tab)
3. Switch to **JSON** tab
4. Paste this:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": "arn:aws:bedrock:ap-south-1::foundation-model/*"
    }
  ]
}
```

5. Click **Next**
6. Policy name: `BedrockInvokeAccess`
7. Click **Create policy**
8. Go back to the user creation tab → Click refresh 🔄
9. Search `BedrockInvokeAccess` → Check it ✅
10. Click **Next** → **Create user**

### Step 3: (Optional) Add S3 Policy — For Issue Memory Across PRs

> Only needed if you want the agent to remember issues across PRs using FAISS + S3. Skip if not needed.

1. Go to IAM → Users → `pr-agent-bot` → **Permissions** tab
2. Click **"Add permissions"** → **"Attach policies directly"**
3. Click **"Create policy"** → JSON tab → Paste:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::YOUR-BUCKET-NAME",
        "arn:aws:s3:::YOUR-BUCKET-NAME/*"
      ]
    }
  ]
}
```

4. Replace `YOUR-BUCKET-NAME` with your actual S3 bucket name
5. Policy name: `PRAgentS3Access`
6. Create policy → Attach to user
7. Add `FAISS_S3_BUCKET` secret in GitHub with your bucket name

### Step 4: Get Access Key Credentials

1. Go to IAM → Users → Click `pr-agent-bot`
2. Go to **"Security credentials"** tab
3. Scroll to **"Access keys"** → Click **"Create access key"**
4. Use case: Select **"Third-party service"**
5. Check the confirmation box → Click **Next** → **Create access key**
6. ⚠️ **Copy both values NOW** (Secret only shows once!):
   - Access key ID (e.g. `AKIA...`)
   - Secret access key (e.g. `wJalr...`)

### Step 5: Add to GitHub Repo Secrets

Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret Name | Value |
|-------------|-------|
| `AWS_ACCESS_KEY_ID` | Paste the Access Key ID |
| `AWS_SECRET_ACCESS_KEY` | Paste the Secret Access Key |
| `AWS_REGION` | `ap-south-1` |
| `FAISS_S3_BUCKET` | *(Optional)* Your S3 bucket name |

> **Note:** These are long-lived credentials — they don't expire unless you manually rotate or delete them.

> **To delete later:** IAM → Users → `pr-agent-bot` → Security credentials → Delete access key (or delete the user entirely).

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
| AWS credentials error | Check secrets — no extra spaces |
| Bedrock access denied | Enable model in AWS console + check IAM |
| No comments on PR | File type not supported (see languages above) |
| Clone failed (Option A) | Check network connectivity |
| Submodule empty | Run `git submodule update --init` |
