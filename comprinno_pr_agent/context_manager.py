import faiss
import numpy as np
import json
import os
import boto3
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from sentence_transformers import SentenceTransformer
from pathlib import Path


S3_BUCKET = os.getenv('FAISS_S3_BUCKET')
S3_PREFIX = os.getenv('FAISS_S3_PREFIX', 'faiss')


class PRContextManager:
    def __init__(self, pr_number: int, index_path: str = ".pr_context"):
        self.pr_number = pr_number
        self.index_path = Path(index_path) / f"pr_{pr_number}"
        self.index_path.mkdir(parents=True, exist_ok=True)

        self.encoder = SentenceTransformer('all-MiniLM-L6-v2')
        self.embedding_dim = 384

        self.index_file = self.index_path / "findings.index"
        self.metadata_file = self.index_path / "findings.json"

        self._download_from_s3()
        self.index = self._load_or_create_index()
        self.metadata = self._load_metadata()

    def _s3_key(self, filename: str, pr_number: int = None) -> str:
        pr = pr_number or self.pr_number
        return f"{S3_PREFIX}/pr_{pr}/{filename}"

    def _download_from_s3(self):
        if not S3_BUCKET:
            return
        try:
            s3 = boto3.client('s3')
            for filename in ['findings.index', 'findings.json']:
                local_path = self.index_path / filename
                try:
                    s3.download_file(S3_BUCKET, self._s3_key(filename), str(local_path))
                    print(f"📥 Downloaded FAISS {filename} from S3 (pr_{self.pr_number})")
                except Exception:
                    pass
        except Exception as e:
            print(f"⚠️  S3 download warning: {e}")

    def _upload_to_s3(self):
        if not S3_BUCKET:
            return
        try:
            s3 = boto3.client('s3')
            for filename in ['findings.index', 'findings.json']:
                local_path = self.index_path / filename
                if local_path.exists():
                    s3.upload_file(str(local_path), S3_BUCKET, self._s3_key(filename))
            print(f"📤 Uploaded FAISS index to S3 (pr_{self.pr_number})")
        except Exception as e:
            print(f"⚠️  S3 upload warning: {e}")

    def _load_or_create_index(self):
        if self.index_file.exists():
            return faiss.read_index(str(self.index_file))
        # Use IndexFlatIP with normalized vectors = cosine similarity
        return faiss.IndexFlatIP(self.embedding_dim)

    def _load_metadata(self) -> List[Dict]:
        if self.metadata_file.exists():
            with open(self.metadata_file, 'r') as f:
                return json.load(f)
        return []

    def _save_index(self):
        faiss.write_index(self.index, str(self.index_file))
        with open(self.metadata_file, 'w') as f:
            json.dump(self.metadata, f, indent=2)
        self._upload_to_s3()

    def is_similar_issue_known(self, finding: Dict, threshold: float = 0.75) -> bool:
        """Check if a semantically similar issue already exists in FAISS"""
        if self.index.ntotal == 0:
            return False
        text = f"{finding.get('category', '')} {finding.get('description', '')} {finding.get('code_snippet', '')}"
        embedding = self.encoder.encode([text])[0]
        embedding = np.array([embedding], dtype=np.float32)
        # Normalize for cosine similarity
        faiss.normalize_L2(embedding)
        distances, _ = self.index.search(embedding, k=1)
        return float(distances[0][0]) >= threshold

    def store_findings(self, findings: List[Dict]):
        """Store findings in FAISS — skip duplicates by category+line+file and semantic similarity"""
        existing_keys = {
            f"{m['category']}:{m['line']}:{m['file']}"
            for m in self.metadata if m['status'] == 'open'
        }
        for finding in findings:
            key = f"{finding.get('category','')}:{finding.get('line_start',0)}:{finding.get('file','')}"
            if key in existing_keys:
                continue
            # Also skip if semantically similar issue already exists
            if self.is_similar_issue_known(finding):
                continue
            existing_keys.add(key)
            text = f"{finding.get('category', '')} {finding.get('description', '')} {finding.get('code_snippet', '')}"
            embedding = self.encoder.encode([text])[0]
            norm_embedding = np.array([embedding], dtype=np.float32)
            faiss.normalize_L2(norm_embedding)
            self.index.add(norm_embedding)
            self.metadata.append({
                'id': len(self.metadata),
                'pr_number': self.pr_number,
                'file': finding.get('file', ''),
                'line': finding.get('line_start', 0),
                'category': finding.get('category', ''),
                'severity': finding.get('severity', ''),
                'description': finding.get('description', ''),
                'code_snippet': finding.get('code_snippet', ''),
                'timestamp': datetime.now().isoformat(),
                'status': 'open'
            })
        self._save_index()

    def get_open_issues_for_files(self, file_paths: List[str]) -> List[Dict]:
        """Get all open issues from ANY previous PR for the given files"""
        return [
            m for m in self.metadata
            if m['status'] == 'open' and m.get('file', '') in file_paths
        ]

    def get_cross_pr_open_issues(self, file_paths: List[str]) -> List[Dict]:
        """
        Download and merge metadata from all PRs in S3,
        return open issues for the given files from any PR.
        """
        if not S3_BUCKET:
            return self.get_open_issues_for_files(file_paths)

        all_issues = []
        try:
            s3 = boto3.client('s3')
            # List all PR metadata files in S3
            paginator = s3.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=f"{S3_PREFIX}/"):
                for obj in page.get('Contents', []):
                    key = obj['Key']
                    if not key.endswith('findings.json'):
                        continue
                    # Skip current PR (already loaded)
                    if f"pr_{self.pr_number}/" in key:
                        continue
                    try:
                        response = s3.get_object(Bucket=S3_BUCKET, Key=key)
                        metadata = json.loads(response['Body'].read())
                        for m in metadata:
                            if m.get('status') == 'open' and m.get('file', '') in file_paths:
                                all_issues.append(m)
                    except Exception:
                        pass
        except Exception as e:
            print(f"⚠️  Cross-PR S3 scan warning: {e}")

        # Also include current PR's open issues
        all_issues.extend(self.get_open_issues_for_files(file_paths))
        return all_issues

    def mark_resolved(self, finding_id: int, pr_number: int = None):
        """Mark a finding as resolved"""
        for m in self.metadata:
            if m['id'] == finding_id and m.get('pr_number', self.pr_number) == (pr_number or self.pr_number):
                m['status'] = 'fixed'
                m['resolved_in_pr'] = self.pr_number
                m['resolved_at'] = datetime.now().isoformat()
        self._save_index()

    def get_open_issues(self) -> List[Dict]:
        return [m for m in self.metadata if m['status'] == 'open']
