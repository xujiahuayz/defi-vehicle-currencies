# P1 robustness check: depth_split

Within-token temporal split at each candidate's OWN median log_vehicle_linked_liquidity over the sample window (high vs low baseline depth). Same 3-equation system, same 3 inference methods, as run_p1_headline_panel.py, run separately on each half.

## Sample
| Sample | N rows | Tokens | First date | Last date |
| --- | --- | --- | --- | --- |
| depth=high | 4710 | 5 | 2021-05-26 | 2026-06-30 |
|   token=DAI | 942 | 1 | 2021-05-26 | 2024-06-20 |
|   token=USDC | 942 | 1 | 2021-10-29 | 2026-01-14 |
|   token=USDT | 942 | 1 | 2021-06-03 | 2026-06-30 |
|   token=WBTC | 942 | 1 | 2021-10-15 | 2026-06-01 |
|   token=WETH | 942 | 1 | 2021-10-19 | 2026-06-11 |
| depth=low | 4705 | 5 | 2021-05-05 | 2026-06-30 |
|   token=DAI | 941 | 1 | 2021-05-05 | 2026-06-30 |
|   token=USDC | 941 | 1 | 2021-05-05 | 2026-06-30 |
|   token=USDT | 941 | 1 | 2021-05-05 | 2025-05-06 |
|   token=WBTC | 941 | 1 | 2021-05-05 | 2026-06-30 |
|   token=WETH | 941 | 1 | 2021-05-05 | 2026-06-30 |

## Results
| Depth regime | Equation | Horizon (days) | Regressor | N | Date clusters | Beta | SE (cluster-by-date) | p (cluster-by-date) | SE (Driscoll-Kraay) | p (Driscoll-Kraay) | SE (month block bootstrap) | Predicted sign (P1) | Sign check |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| high | outcome=S | 1 | L | 4,709 | 1,805 | 0.0612 | 0.0042 | <0.001 | 0.0052 | <0.001 | 0.0065 | + | MATCH (p<.05, DK) |
| high | outcome=S | 1 | D | 4,709 | 1,805 | -0.0203 | 0.0074 | 0.006 | 0.0065 | 0.002 | 0.0076 | - | MATCH (p<.05, DK) |
| high | outcome=S | 1 | S | 4,709 | 1,805 | -0.4007 | 0.0244 | <0.001 | 0.0271 | <0.001 | 0.0315 | (no prior) | n/a (no P1 prior) |
| high | outcome=S | 7 | L | 4,703 | 1,799 | 0.0791 | 0.0041 | <0.001 | 0.0059 | <0.001 | 0.0065 | + | MATCH (p<.05, DK) |
| high | outcome=S | 7 | D | 4,703 | 1,799 | -0.0124 | 0.0073 | 0.090 | 0.0085 | 0.145 | 0.0090 | - | sign matches but not sig. (DK p=0.145) |
| high | outcome=S | 7 | S | 4,703 | 1,799 | -0.5178 | 0.0230 | <0.001 | 0.0297 | <0.001 | 0.0354 | (no prior) | n/a (no P1 prior) |
| high | outcome=S | 14 | L | 4,696 | 1,792 | 0.0840 | 0.0041 | <0.001 | 0.0072 | <0.001 | 0.0077 | + | MATCH (p<.05, DK) |
| high | outcome=S | 14 | D | 4,696 | 1,792 | -0.0333 | 0.0079 | <0.001 | 0.0115 | 0.004 | 0.0134 | - | MATCH (p<.05, DK) |
| high | outcome=S | 14 | S | 4,696 | 1,792 | -0.5687 | 0.0231 | <0.001 | 0.0332 | <0.001 | 0.0358 | (no prior) | n/a (no P1 prior) |
| high | outcome=S | 30 | L | 4,675 | 1,776 | 0.0920 | 0.0041 | <0.001 | 0.0096 | <0.001 | 0.0087 | + | MATCH (p<.05, DK) |
| high | outcome=S | 30 | D | 4,675 | 1,776 | -0.0377 | 0.0087 | <0.001 | 0.0142 | 0.008 | 0.0151 | - | MATCH (p<.05, DK) |
| high | outcome=S | 30 | S | 4,675 | 1,776 | -0.6455 | 0.0224 | <0.001 | 0.0404 | <0.001 | 0.0403 | (no prior) | n/a (no P1 prior) |
| high | outcome=L | 1 | S | 4,709 | 1,805 | 0.0439 | 0.0197 | 0.026 | 0.0196 | 0.025 | 0.0199 | + | MATCH (p<.05, DK) |
| high | outcome=L | 1 | D | 4,709 | 1,805 | -0.0011 | 0.0037 | 0.765 | 0.0034 | 0.743 | 0.0036 | (no prior) | n/a (no P1 prior) |
| high | outcome=L | 1 | L | 4,709 | 1,805 | -0.0143 | 0.0062 | 0.021 | 0.0062 | 0.022 | 0.0068 | (no prior) | n/a (no P1 prior) |
| high | outcome=L | 7 | S | 4,703 | 1,799 | 0.0760 | 0.0222 | <0.001 | 0.0268 | 0.005 | 0.0265 | + | MATCH (p<.05, DK) |
| high | outcome=L | 7 | D | 4,703 | 1,799 | -0.0176 | 0.0057 | 0.002 | 0.0081 | 0.030 | 0.0083 | (no prior) | n/a (no P1 prior) |
| high | outcome=L | 7 | L | 4,703 | 1,799 | -0.0237 | 0.0066 | <0.001 | 0.0080 | 0.003 | 0.0088 | (no prior) | n/a (no P1 prior) |
| high | outcome=L | 14 | S | 4,696 | 1,792 | 0.1089 | 0.0253 | <0.001 | 0.0388 | 0.005 | 0.0348 | + | MATCH (p<.05, DK) |
| high | outcome=L | 14 | D | 4,696 | 1,792 | -0.0330 | 0.0072 | <0.001 | 0.0145 | 0.023 | 0.0161 | (no prior) | n/a (no P1 prior) |
| high | outcome=L | 14 | L | 4,696 | 1,792 | -0.0324 | 0.0073 | <0.001 | 0.0116 | 0.005 | 0.0120 | (no prior) | n/a (no P1 prior) |
| high | outcome=L | 30 | S | 4,675 | 1,776 | 0.1409 | 0.0256 | <0.001 | 0.0549 | 0.010 | 0.0560 | + | MATCH (p<.05, DK) |
| high | outcome=L | 30 | D | 4,675 | 1,776 | -0.0540 | 0.0100 | <0.001 | 0.0272 | 0.047 | 0.0273 | (no prior) | n/a (no P1 prior) |
| high | outcome=L | 30 | L | 4,675 | 1,776 | -0.0392 | 0.0074 | <0.001 | 0.0216 | 0.070 | 0.0203 | (no prior) | n/a (no P1 prior) |
| high | outcome=D | 1 | L | 4,709 | 1,805 | -0.0245 | 0.0062 | <0.001 | 0.0058 | <0.001 | 0.0097 | - | MATCH (p<.05, DK) |
| high | outcome=D | 1 | S | 4,709 | 1,805 | -0.1040 | 0.0275 | <0.001 | 0.0254 | <0.001 | 0.0276 | (no prior) | n/a (no P1 prior) |
| high | outcome=D | 1 | D | 4,709 | 1,805 | -0.4486 | 0.0231 | <0.001 | 0.0282 | <0.001 | 0.0421 | (no prior) | n/a (no P1 prior) |
| high | outcome=D | 7 | L | 4,703 | 1,799 | -0.0244 | 0.0073 | <0.001 | 0.0092 | 0.008 | 0.0137 | - | MATCH (p<.05, DK) |
| high | outcome=D | 7 | S | 4,703 | 1,799 | -0.1272 | 0.0343 | <0.001 | 0.0417 | 0.002 | 0.0420 | (no prior) | n/a (no P1 prior) |
| high | outcome=D | 7 | D | 4,703 | 1,799 | -0.5401 | 0.0234 | <0.001 | 0.0332 | <0.001 | 0.0500 | (no prior) | n/a (no P1 prior) |
| high | outcome=D | 14 | L | 4,696 | 1,792 | -0.0372 | 0.0076 | <0.001 | 0.0119 | 0.002 | 0.0175 | - | MATCH (p<.05, DK) |
| high | outcome=D | 14 | S | 4,696 | 1,792 | -0.0905 | 0.0345 | 0.009 | 0.0528 | 0.087 | 0.0540 | (no prior) | n/a (no P1 prior) |
| high | outcome=D | 14 | D | 4,696 | 1,792 | -0.6221 | 0.0224 | <0.001 | 0.0394 | <0.001 | 0.0486 | (no prior) | n/a (no P1 prior) |
| high | outcome=D | 30 | L | 4,675 | 1,776 | -0.0236 | 0.0077 | 0.002 | 0.0137 | 0.084 | 0.0181 | - | sign matches but not sig. (DK p=0.084) |
| high | outcome=D | 30 | S | 4,675 | 1,776 | -0.1571 | 0.0375 | <0.001 | 0.0714 | 0.028 | 0.0688 | (no prior) | n/a (no P1 prior) |
| high | outcome=D | 30 | D | 4,675 | 1,776 | -0.6489 | 0.0228 | <0.001 | 0.0453 | <0.001 | 0.0432 | (no prior) | n/a (no P1 prior) |
| low | outcome=S | 1 | L | 4,701 | 1,795 | 0.0416 | 0.0023 | <0.001 | 0.0025 | <0.001 | 0.0038 | + | MATCH (p<.05, DK) |
| low | outcome=S | 1 | D | 4,701 | 1,795 | 0.0184 | 0.0053 | <0.001 | 0.0055 | <0.001 | 0.0086 | - | WRONG SIGN (predicted -, got +) |
| low | outcome=S | 1 | S | 4,701 | 1,795 | -0.3776 | 0.0204 | <0.001 | 0.0233 | <0.001 | 0.0329 | (no prior) | n/a (no P1 prior) |
| low | outcome=S | 7 | L | 4,677 | 1,789 | 0.0555 | 0.0027 | <0.001 | 0.0034 | <0.001 | 0.0042 | + | MATCH (p<.05, DK) |
| low | outcome=S | 7 | D | 4,677 | 1,789 | 0.0121 | 0.0067 | 0.072 | 0.0087 | 0.163 | 0.0114 | - | WRONG SIGN (predicted -, got +) |
| low | outcome=S | 7 | S | 4,677 | 1,789 | -0.5246 | 0.0232 | <0.001 | 0.0301 | <0.001 | 0.0306 | (no prior) | n/a (no P1 prior) |
| low | outcome=S | 14 | L | 4,649 | 1,782 | 0.0632 | 0.0027 | <0.001 | 0.0042 | <0.001 | 0.0050 | + | MATCH (p<.05, DK) |
| low | outcome=S | 14 | D | 4,649 | 1,782 | 0.0106 | 0.0066 | 0.109 | 0.0104 | 0.311 | 0.0118 | - | WRONG SIGN (predicted -, got +) |
| low | outcome=S | 14 | S | 4,649 | 1,782 | -0.5971 | 0.0250 | <0.001 | 0.0461 | <0.001 | 0.0591 | (no prior) | n/a (no P1 prior) |
| low | outcome=S | 30 | L | 4,590 | 1,766 | 0.0719 | 0.0025 | <0.001 | 0.0042 | <0.001 | 0.0054 | + | MATCH (p<.05, DK) |
| low | outcome=S | 30 | D | 4,590 | 1,766 | 0.0204 | 0.0070 | 0.004 | 0.0156 | 0.191 | 0.0175 | - | WRONG SIGN (predicted -, got +) |
| low | outcome=S | 30 | S | 4,590 | 1,766 | -0.6645 | 0.0220 | <0.001 | 0.0443 | <0.001 | 0.0437 | (no prior) | n/a (no P1 prior) |
| low | outcome=L | 1 | S | 4,701 | 1,795 | 0.0220 | 0.0130 | 0.092 | 0.0133 | 0.099 | 0.0153 | + | sign matches but not sig. (DK p=0.099) |
| low | outcome=L | 1 | D | 4,701 | 1,795 | -0.0031 | 0.0045 | 0.488 | 0.0042 | 0.462 | 0.0046 | (no prior) | n/a (no P1 prior) |
| low | outcome=L | 1 | L | 4,701 | 1,795 | -0.0009 | 0.0018 | 0.605 | 0.0020 | 0.638 | 0.0034 | (no prior) | n/a (no P1 prior) |
| low | outcome=L | 7 | S | 4,677 | 1,789 | 0.0098 | 0.0189 | 0.603 | 0.0286 | 0.731 | 0.0268 | + | sign matches but not sig. (DK p=0.731) |
| low | outcome=L | 7 | D | 4,677 | 1,789 | -0.0123 | 0.0090 | 0.171 | 0.0115 | 0.283 | 0.0115 | (no prior) | n/a (no P1 prior) |
| low | outcome=L | 7 | L | 4,677 | 1,789 | -0.0003 | 0.0031 | 0.930 | 0.0051 | 0.958 | 0.0080 | (no prior) | n/a (no P1 prior) |
| low | outcome=L | 14 | S | 4,649 | 1,782 | -0.0503 | 0.0234 | 0.032 | 0.0345 | 0.145 | 0.0382 | + | WRONG SIGN (predicted +, got -) |
| low | outcome=L | 14 | D | 4,649 | 1,782 | 0.0030 | 0.0099 | 0.758 | 0.0160 | 0.849 | 0.0171 | (no prior) | n/a (no P1 prior) |
| low | outcome=L | 14 | L | 4,649 | 1,782 | 0.0103 | 0.0038 | 0.006 | 0.0061 | 0.089 | 0.0103 | (no prior) | n/a (no P1 prior) |
| low | outcome=L | 30 | S | 4,590 | 1,766 | -0.0482 | 0.0240 | 0.044 | 0.0488 | 0.324 | 0.0502 | + | WRONG SIGN (predicted +, got -) |
| low | outcome=L | 30 | D | 4,590 | 1,766 | 0.0186 | 0.0137 | 0.176 | 0.0302 | 0.538 | 0.0297 | (no prior) | n/a (no P1 prior) |
| low | outcome=L | 30 | L | 4,590 | 1,766 | 0.0254 | 0.0038 | <0.001 | 0.0089 | 0.004 | 0.0181 | (no prior) | n/a (no P1 prior) |
| low | outcome=D | 1 | L | 4,701 | 1,795 | -0.0449 | 0.0041 | <0.001 | 0.0057 | <0.001 | 0.0138 | - | MATCH (p<.05, DK) |
| low | outcome=D | 1 | S | 4,701 | 1,795 | 0.0587 | 0.0214 | 0.006 | 0.0221 | 0.008 | 0.0333 | (no prior) | n/a (no P1 prior) |
| low | outcome=D | 1 | D | 4,701 | 1,795 | -0.5213 | 0.0253 | <0.001 | 0.0348 | <0.001 | 0.0514 | (no prior) | n/a (no P1 prior) |
| low | outcome=D | 7 | L | 4,677 | 1,789 | -0.0541 | 0.0042 | <0.001 | 0.0068 | <0.001 | 0.0151 | - | MATCH (p<.05, DK) |
| low | outcome=D | 7 | S | 4,677 | 1,789 | 0.0545 | 0.0228 | 0.017 | 0.0314 | 0.083 | 0.0440 | (no prior) | n/a (no P1 prior) |
| low | outcome=D | 7 | D | 4,677 | 1,789 | -0.6360 | 0.0243 | <0.001 | 0.0333 | <0.001 | 0.0479 | (no prior) | n/a (no P1 prior) |
| low | outcome=D | 14 | L | 4,649 | 1,782 | -0.0617 | 0.0043 | <0.001 | 0.0078 | <0.001 | 0.0165 | - | MATCH (p<.05, DK) |
| low | outcome=D | 14 | S | 4,649 | 1,782 | 0.0640 | 0.0250 | 0.011 | 0.0416 | 0.124 | 0.0470 | (no prior) | n/a (no P1 prior) |
| low | outcome=D | 14 | D | 4,649 | 1,782 | -0.7078 | 0.0241 | <0.001 | 0.0382 | <0.001 | 0.0410 | (no prior) | n/a (no P1 prior) |
| low | outcome=D | 30 | L | 4,590 | 1,766 | -0.0731 | 0.0042 | <0.001 | 0.0103 | <0.001 | 0.0193 | - | MATCH (p<.05, DK) |
| low | outcome=D | 30 | S | 4,590 | 1,766 | 0.1014 | 0.0235 | <0.001 | 0.0527 | 0.055 | 0.0548 | (no prior) | n/a (no P1 prior) |
| low | outcome=D | 30 | D | 4,590 | 1,766 | -0.7578 | 0.0221 | <0.001 | 0.0444 | <0.001 | 0.0464 | (no prior) | n/a (no P1 prior) |

