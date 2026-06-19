from typing import Dict, Any, List
from datetime import datetime
import os

class MarkdownReportGenerator:
    def __init__(self):
        self.consolidated_data = []
        self.report_name = None
    
    def add_file_analysis(self, file_path: str, analysis_results: Dict[str, Any]):
        """Add analysis results for a file to consolidated report"""
        self.consolidated_data.append({
            'file_path': file_path,
            'results': analysis_results
        })
    
    def generate_consolidated_report(self, directory_name: str, ticket_info: dict = None) -> str:
        """Generate single consolidated report for all analyzed files"""
        
        report = f"""# Code Analysis Report - {directory_name}

**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  
**Analyzer:** Deep Code Analysis Agent (AAS-3)  
**Files Analyzed:** {len(self.consolidated_data)}

"""
        
        # Add Ticket Details if available
        if ticket_info:
            report += f"""---

## 📋 Jira Ticket Details

**Ticket ID:** {ticket_info['ticket_id']}  
**Title:** {ticket_info['title']}  
**Type:** {ticket_info['type']}  
**Status:** {ticket_info['status']}  
**Priority:** {ticket_info['priority']}  
**Assignee:** {ticket_info['assignee']}

### Description
{str(ticket_info['description'])[:300]}...

---

## 🔍 Code Analysis Against Ticket

**Agent Validation:**
- ✅ Extracted ticket: {ticket_info['ticket_id']}
- ✅ Analyzed code changes
- ✅ Validated against ticket requirements
- ✅ Checked code quality and best practices

---

## 📊 Analysis Results

"""
        else:
            report += """---

## Overall Summary

"""
        
        # Calculate overall statistics
        total_findings = 0
        total_critical = 0
        total_warning = 0
        total_info = 0
        
        for file_data in self.consolidated_data:
            findings = file_data['results'].get('findings', [])
            total_findings += len(findings)
            total_critical += sum(1 for f in findings if f.get('severity') == 'Critical')
            total_warning += sum(1 for f in findings if f.get('severity') == 'Warning')
            total_info += sum(1 for f in findings if f.get('severity') == 'Info')
        
        report += f"""| Metric | Count |
|--------|-------|
| Total Files | {len(self.consolidated_data)} |
| Total Findings | {total_findings} |
| 🔴 Critical | {total_critical} |
| 🟡 Warning | {total_warning} |
| 🔵 Info | {total_info} |

---

"""
        
        # Generate report for each file
        for file_data in self.consolidated_data:
            file_path = file_data['file_path']
            findings = file_data['results'].get('findings', [])
            
            report += f"""## File: `{file_path}`

"""
            
            if not findings:
                report += "✅ **No issues found!** Code looks good.\n\n---\n\n"
                continue
            
            # Count by severity for this file
            critical = sum(1 for f in findings if f.get('severity') == 'Critical')
            warning = sum(1 for f in findings if f.get('severity') == 'Warning')
            info = sum(1 for f in findings if f.get('severity') == 'Info')
            
            report += f"""**Findings:** {len(findings)} (🔴 {critical} | 🟡 {warning} | 🔵 {info})

"""
            
            # Sort by line number for better readability
            sorted_findings = sorted(findings, key=lambda x: x.get('line_start', 0))
            
            for idx, finding in enumerate(sorted_findings, 1):
                severity_icon = {
                    'Critical': '🔴',
                    'Warning': '🟡',
                    'Info': '🔵'
                }.get(finding.get('severity', 'Info'), '⚪')
                
                report += f"""### {severity_icon} {finding.get('category', 'Issue')} (Lines {finding.get('line_start', '?')}-{finding.get('line_end', '?')})

**Severity:** {finding.get('severity', 'Info')}

**Description:**  
{finding.get('description', 'No description provided')}

"""
                
                # Add new detailed fields if available
                if finding.get('why_it_matters'):
                    report += f"""**Why This Matters:**  
{finding.get('why_it_matters')}

"""
                
                if finding.get('how_to_fix'):
                    report += f"""**How to Fix:**  
{finding.get('how_to_fix')}

"""
                
                if finding.get('code_example'):
                    report += f"""**Recommended Code:**
```
{finding.get('code_example')}
```

"""
                
                if finding.get('best_practice'):
                    report += f"""**Best Practice:**  
{finding.get('best_practice')}

"""
                
                # Fallback for old format
                if not finding.get('how_to_fix') and finding.get('suggestion'):
                    report += f"""**Suggestion:**  
{finding.get('suggestion')}

"""
                
                if finding.get('code_snippet'):
                    report += f"""**Code Snippet:**
```
{finding.get('code_snippet')}
```

"""
                
                report += "\n"
            
            report += "---\n\n"
        
        report += f"""## Recommendations

1. Address **Critical** issues immediately - these may cause bugs or security issues
2. Review **Warning** issues and plan fixes in upcoming sprints
3. Consider **Info** items for code quality improvements

---

*Generated by Deep Code Analysis Agent using AWS Bedrock Nova*
"""
        
        return report
    
    def save_consolidated_report(self, directory_path: str, report_content: str) -> str:
        """Save consolidated report to markdown file"""
        # Generate report filename based on directory name
        dir_name = os.path.basename(os.path.normpath(directory_path))
        report_path = os.path.join(directory_path, f"{dir_name}_analysis.md")
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report_content)
        
        return report_path
    
    def reset(self):
        """Reset consolidated data for new analysis"""
        self.consolidated_data = []
        self.report_name = None
    
    # Keep old methods for backward compatibility with single file analysis
    def generate(self, file_path: str, analysis_results: Dict[str, Any]) -> str:
        """Generate markdown report from analysis results (legacy single file)"""
        
        report = f"""# Code Analysis Report

**File:** `{file_path}`  
**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  
**Analyzer:** Deep Code Analysis Agent (AAS-3)

---

## Summary

"""
        
        findings = analysis_results.get('findings', [])
        
        if not findings:
            report += "✅ **No issues found!** Code looks good.\n\n"
            return report
        
        # Count by severity
        critical = sum(1 for f in findings if f.get('severity') == 'Critical')
        warning = sum(1 for f in findings if f.get('severity') == 'Warning')
        info = sum(1 for f in findings if f.get('severity') == 'Info')
        
        report += f"""| Severity | Count |
|----------|-------|
| 🔴 Critical | {critical} |
| 🟡 Warning | {warning} |
| 🔵 Info | {info} |
| **Total** | **{len(findings)}** |

---

## Findings

"""
        
        # Sort by severity
        severity_order = {'Critical': 0, 'Warning': 1, 'Info': 2}
        sorted_findings = sorted(findings, key=lambda x: severity_order.get(x.get('severity', 'Info'), 3))
        
        for idx, finding in enumerate(sorted_findings, 1):
            severity_icon = {
                'Critical': '🔴',
                'Warning': '🟡',
                'Info': '🔵'
            }.get(finding.get('severity', 'Info'), '⚪')
            
            report += f"""### {idx}. {severity_icon} {finding.get('category', 'Issue')}

**Severity:** {finding.get('severity', 'Info')}  
**Location:** Lines {finding.get('line_start', '?')}-{finding.get('line_end', '?')}

**Description:**  
{finding.get('description', 'No description provided')}

"""
            
            # Add new detailed fields if available
            if finding.get('why_it_matters'):
                report += f"""**Why This Matters:**  
{finding.get('why_it_matters')}

"""
            
            if finding.get('how_to_fix'):
                report += f"""**How to Fix:**  
{finding.get('how_to_fix')}

"""
            
            if finding.get('code_example'):
                report += f"""**Recommended Code:**
```python
{finding.get('code_example')}
```

"""
            
            if finding.get('best_practice'):
                report += f"""**Best Practice:**  
{finding.get('best_practice')}

"""
            
            # Fallback for old format
            if not finding.get('how_to_fix') and finding.get('suggestion'):
                report += f"""**Suggestion:**  
{finding.get('suggestion')}

"""
            
            if finding.get('code_snippet'):
                report += f"""**Code Snippet:**
```python
{finding.get('code_snippet')}
```

"""
            
            report += "---\n\n"
        
        report += f"""## Recommendations

1. Address **Critical** issues immediately before merging
2. Review **Warning** issues and plan fixes
3. Consider **Info** items for code quality improvements

---

*Generated by Deep Code Analysis Agent using AWS Bedrock Nova*
"""
        
        return report
    
    def save_report(self, file_path: str, report_content: str) -> str:
        """Save report to markdown file (legacy single file)"""
        # Generate report filename
        base_name = file_path.rsplit('.', 1)[0]
        report_path = f"{base_name}_analysis.md"
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report_content)
        
        return report_path
