# Code Reviewer Evaluation Results

## Evaluation Runs Summary

| Run | Recall | Precision | False Positives | Matched Bug Descriptions | Missed Bug Descriptions |
| --- | --- | --- | --- | --- | --- |
| Run 1 | 1.00 (100%) | 0.75 (75%) | 1 | • Off-by-one loop condition (i > 1 instead of i >= 1) omits rotating .1 to .2, causing the first backup log to be overwritten.<br>• Flipped comparison operator (!== instead of ===) in verifyOtp causes verification to succeed for invalid OTPs and fail for valid ones.<br>• Missing await on notifyService.update() causes an unresolved Promise object rather than the updated notification record to be returned in the response. | None |
| Run 2 | 1.00 (100%) | 0.75 (75%) | 1 | • Off-by-one loop condition (i > 1 instead of i >= 1) omits rotating .1 to .2, causing the first backup log to be overwritten.<br>• Flipped comparison operator (!== instead of ===) in verifyOtp causes verification to succeed for invalid OTPs and fail for valid ones.<br>• Missing await on notifyService.update() causes an unresolved Promise object rather than the updated notification record to be returned in the response. | None |
| Run 3 | 1.00 (100%) | 0.75 (75%) | 1 | • Off-by-one loop condition (i > 1 instead of i >= 1) omits rotating .1 to .2, causing the first backup log to be overwritten.<br>• Flipped comparison operator (!== instead of ===) in verifyOtp causes verification to succeed for invalid OTPs and fail for valid ones.<br>• Missing await on notifyService.update() causes an unresolved Promise object rather than the updated notification record to be returned in the response. | None |

### Consistency Summary
Both recall (1.00) and precision (0.75) were consistent across all 3 evaluation runs with no variance.

## Methodology and Limitations

### Matching Rule
The matching rule compares findings to ground truth entries using exact file path equality and line proximity:
- File paths are normalized to be repository-relative, requiring an exact match (`normalize_path(finding.file) == ground_truth["file"]`).
- Line numbers are matched within a tolerance of ±3 lines (`abs(finding_line - ground_truth_line) <= 3`), using the first integer in any range or string format. If either line number cannot be parsed, the finding is treated as non-matching.

### Known Limitation
This heuristic cannot distinguish a correct diagnosis from a finding that locates the right line but reasons about it incorrectly (this happened with the otpService bug in manual testing — a finding can match by location while its suggested fix is actually wrong or a no-op).
