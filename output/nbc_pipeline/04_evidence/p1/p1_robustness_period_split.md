# P1 robustness check: period_split

Chronological split at the sample's midpoint date (2023-12-02): no exogenous shock date is used anywhere in the headline lead-lag design (see run_p1_headline_panel.py docstring), so this is the analogous split named in the task instructions, not a pre/post-shock split. Same system/inference as headline.

## Sample
| Sample | N rows | Tokens | First date | Last date |
| --- | --- | --- | --- | --- |
| period=pre (split at 2023-12-02) | 4705 | 5 | 2021-05-05 | 2023-12-01 |
|   token=DAI | 941 | 1 | 2021-05-05 | 2023-12-01 |
|   token=USDC | 941 | 1 | 2021-05-05 | 2023-12-01 |
|   token=USDT | 941 | 1 | 2021-05-05 | 2023-12-01 |
|   token=WBTC | 941 | 1 | 2021-05-05 | 2023-12-01 |
|   token=WETH | 941 | 1 | 2021-05-05 | 2023-12-01 |
| period=post (split at 2023-12-02) | 4710 | 5 | 2023-12-02 | 2026-06-30 |
|   token=DAI | 942 | 1 | 2023-12-02 | 2026-06-30 |
|   token=USDC | 942 | 1 | 2023-12-02 | 2026-06-30 |
|   token=USDT | 942 | 1 | 2023-12-02 | 2026-06-30 |
|   token=WBTC | 942 | 1 | 2023-12-02 | 2026-06-30 |
|   token=WETH | 942 | 1 | 2023-12-02 | 2026-06-30 |

## Results
| Period | Equation | Horizon (days) | Regressor | N | Date clusters | Beta | SE (cluster-by-date) | p (cluster-by-date) | SE (Driscoll-Kraay) | p (Driscoll-Kraay) | SE (month block bootstrap) | Predicted sign (P1) | Sign check |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pre | outcome=S | 1 | L | 4,705 | 941 | 0.0250 | 0.0032 | <0.001 | 0.0029 | <0.001 | 0.0046 | + | MATCH (p<.05, DK) |
| pre | outcome=S | 1 | D | 4,705 | 941 | -0.0045 | 0.0040 | 0.262 | 0.0043 | 0.297 | 0.0064 | - | sign matches but not sig. (DK p=0.297) |
| pre | outcome=S | 1 | S | 4,705 | 941 | -0.4261 | 0.0217 | <0.001 | 0.0247 | <0.001 | 0.0407 | (no prior) | n/a (no P1 prior) |
| pre | outcome=S | 7 | L | 4,705 | 941 | 0.0228 | 0.0035 | <0.001 | 0.0055 | <0.001 | 0.0071 | + | MATCH (p<.05, DK) |
| pre | outcome=S | 7 | D | 4,705 | 941 | 0.0017 | 0.0046 | 0.706 | 0.0056 | 0.756 | 0.0070 | - | WRONG SIGN (predicted -, got +) |
| pre | outcome=S | 7 | S | 4,705 | 941 | -0.5918 | 0.0230 | <0.001 | 0.0307 | <0.001 | 0.0319 | (no prior) | n/a (no P1 prior) |
| pre | outcome=S | 14 | L | 4,705 | 941 | 0.0216 | 0.0037 | <0.001 | 0.0079 | 0.006 | 0.0096 | + | MATCH (p<.05, DK) |
| pre | outcome=S | 14 | D | 4,705 | 941 | -0.0034 | 0.0042 | 0.409 | 0.0067 | 0.608 | 0.0079 | - | sign matches but not sig. (DK p=0.608) |
| pre | outcome=S | 14 | S | 4,705 | 941 | -0.6900 | 0.0248 | <0.001 | 0.0404 | <0.001 | 0.0456 | (no prior) | n/a (no P1 prior) |
| pre | outcome=S | 30 | L | 4,705 | 941 | 0.0218 | 0.0034 | <0.001 | 0.0095 | 0.021 | 0.0101 | + | MATCH (p<.05, DK) |
| pre | outcome=S | 30 | D | 4,705 | 941 | -0.0025 | 0.0048 | 0.600 | 0.0095 | 0.791 | 0.0102 | - | sign matches but not sig. (DK p=0.791) |
| pre | outcome=S | 30 | S | 4,705 | 941 | -0.7825 | 0.0230 | <0.001 | 0.0428 | <0.001 | 0.0406 | (no prior) | n/a (no P1 prior) |
| pre | outcome=L | 1 | S | 4,705 | 941 | 0.0214 | 0.0124 | 0.085 | 0.0128 | 0.095 | 0.0155 | + | sign matches but not sig. (DK p=0.095) |
| pre | outcome=L | 1 | D | 4,705 | 941 | -0.0109 | 0.0046 | 0.018 | 0.0048 | 0.022 | 0.0039 | (no prior) | n/a (no P1 prior) |
| pre | outcome=L | 1 | L | 4,705 | 941 | -0.0180 | 0.0076 | 0.019 | 0.0082 | 0.027 | 0.0092 | (no prior) | n/a (no P1 prior) |
| pre | outcome=L | 7 | S | 4,705 | 941 | 0.0366 | 0.0178 | 0.040 | 0.0262 | 0.162 | 0.0194 | + | sign matches but not sig. (DK p=0.162) |
| pre | outcome=L | 7 | D | 4,705 | 941 | -0.0230 | 0.0095 | 0.016 | 0.0138 | 0.096 | 0.0165 | (no prior) | n/a (no P1 prior) |
| pre | outcome=L | 7 | L | 4,705 | 941 | -0.0537 | 0.0102 | <0.001 | 0.0191 | 0.005 | 0.0244 | (no prior) | n/a (no P1 prior) |
| pre | outcome=L | 14 | S | 4,705 | 941 | 0.0456 | 0.0224 | 0.042 | 0.0409 | 0.265 | 0.0472 | + | sign matches but not sig. (DK p=0.265) |
| pre | outcome=L | 14 | D | 4,705 | 941 | -0.0603 | 0.0137 | <0.001 | 0.0266 | 0.024 | 0.0305 | (no prior) | n/a (no P1 prior) |
| pre | outcome=L | 14 | L | 4,705 | 941 | -0.0904 | 0.0127 | <0.001 | 0.0326 | 0.006 | 0.0377 | (no prior) | n/a (no P1 prior) |
| pre | outcome=L | 30 | S | 4,705 | 941 | 0.0642 | 0.0257 | 0.013 | 0.0489 | 0.190 | 0.0484 | + | sign matches but not sig. (DK p=0.190) |
| pre | outcome=L | 30 | D | 4,705 | 941 | -0.1345 | 0.0191 | <0.001 | 0.0533 | 0.012 | 0.0513 | (no prior) | n/a (no P1 prior) |
| pre | outcome=L | 30 | L | 4,705 | 941 | -0.1524 | 0.0139 | <0.001 | 0.0519 | 0.003 | 0.0551 | (no prior) | n/a (no P1 prior) |
| pre | outcome=D | 1 | L | 4,705 | 941 | 0.0192 | 0.0117 | 0.100 | 0.0112 | 0.087 | 0.0134 | - | WRONG SIGN (predicted -, got +) |
| pre | outcome=D | 1 | S | 4,705 | 941 | -0.0252 | 0.0177 | 0.155 | 0.0171 | 0.141 | 0.0233 | (no prior) | n/a (no P1 prior) |
| pre | outcome=D | 1 | D | 4,705 | 941 | -0.6198 | 0.0266 | <0.001 | 0.0353 | <0.001 | 0.0458 | (no prior) | n/a (no P1 prior) |
| pre | outcome=D | 7 | L | 4,705 | 941 | 0.0263 | 0.0120 | 0.029 | 0.0157 | 0.094 | 0.0209 | - | WRONG SIGN (predicted -, got +) |
| pre | outcome=D | 7 | S | 4,705 | 941 | -0.0255 | 0.0189 | 0.177 | 0.0257 | 0.321 | 0.0306 | (no prior) | n/a (no P1 prior) |
| pre | outcome=D | 7 | D | 4,705 | 941 | -0.7894 | 0.0247 | <0.001 | 0.0312 | <0.001 | 0.0342 | (no prior) | n/a (no P1 prior) |
| pre | outcome=D | 14 | L | 4,705 | 941 | 0.0285 | 0.0121 | 0.019 | 0.0178 | 0.110 | 0.0204 | - | WRONG SIGN (predicted -, got +) |
| pre | outcome=D | 14 | S | 4,705 | 941 | -0.0156 | 0.0210 | 0.458 | 0.0305 | 0.609 | 0.0356 | (no prior) | n/a (no P1 prior) |
| pre | outcome=D | 14 | D | 4,705 | 941 | -0.8770 | 0.0238 | <0.001 | 0.0335 | <0.001 | 0.0389 | (no prior) | n/a (no P1 prior) |
| pre | outcome=D | 30 | L | 4,705 | 941 | 0.0327 | 0.0120 | 0.007 | 0.0245 | 0.183 | 0.0292 | - | WRONG SIGN (predicted -, got +) |
| pre | outcome=D | 30 | S | 4,705 | 941 | -0.0181 | 0.0183 | 0.323 | 0.0380 | 0.634 | 0.0414 | (no prior) | n/a (no P1 prior) |
| pre | outcome=D | 30 | D | 4,705 | 941 | -0.8534 | 0.0233 | <0.001 | 0.0413 | <0.001 | 0.0394 | (no prior) | n/a (no P1 prior) |
| post | outcome=S | 1 | L | 4,705 | 941 | 0.0520 | 0.0059 | <0.001 | 0.0076 | <0.001 | 0.0149 | + | MATCH (p<.05, DK) |
| post | outcome=S | 1 | D | 4,705 | 941 | -0.0054 | 0.0051 | 0.290 | 0.0052 | 0.302 | 0.0070 | - | sign matches but not sig. (DK p=0.302) |
| post | outcome=S | 1 | S | 4,705 | 941 | -0.5208 | 0.0310 | <0.001 | 0.0366 | <0.001 | 0.0485 | (no prior) | n/a (no P1 prior) |
| post | outcome=S | 7 | L | 4,675 | 935 | 0.0625 | 0.0064 | <0.001 | 0.0101 | <0.001 | 0.0162 | + | MATCH (p<.05, DK) |
| post | outcome=S | 7 | D | 4,675 | 935 | -0.0084 | 0.0051 | 0.101 | 0.0067 | 0.209 | 0.0096 | - | sign matches but not sig. (DK p=0.209) |
| post | outcome=S | 7 | S | 4,675 | 935 | -0.6489 | 0.0290 | <0.001 | 0.0344 | <0.001 | 0.0433 | (no prior) | n/a (no P1 prior) |
| post | outcome=S | 14 | L | 4,640 | 928 | 0.0592 | 0.0068 | <0.001 | 0.0137 | <0.001 | 0.0169 | + | MATCH (p<.05, DK) |
| post | outcome=S | 14 | D | 4,640 | 928 | -0.0172 | 0.0053 | 0.001 | 0.0091 | 0.061 | 0.0124 | - | sign matches but not sig. (DK p=0.061) |
| post | outcome=S | 14 | S | 4,640 | 928 | -0.6913 | 0.0282 | <0.001 | 0.0421 | <0.001 | 0.0448 | (no prior) | n/a (no P1 prior) |
| post | outcome=S | 30 | L | 4,560 | 912 | 0.0519 | 0.0071 | <0.001 | 0.0187 | 0.006 | 0.0185 | + | MATCH (p<.05, DK) |
| post | outcome=S | 30 | D | 4,560 | 912 | -0.0222 | 0.0057 | <0.001 | 0.0105 | 0.035 | 0.0113 | - | MATCH (p<.05, DK) |
| post | outcome=S | 30 | S | 4,560 | 912 | -0.7737 | 0.0240 | <0.001 | 0.0408 | <0.001 | 0.0427 | (no prior) | n/a (no P1 prior) |
| post | outcome=L | 1 | S | 4,705 | 941 | 0.0364 | 0.0196 | 0.063 | 0.0231 | 0.116 | 0.0243 | + | sign matches but not sig. (DK p=0.116) |
| post | outcome=L | 1 | D | 4,705 | 941 | -0.0015 | 0.0035 | 0.671 | 0.0035 | 0.672 | 0.0044 | (no prior) | n/a (no P1 prior) |
| post | outcome=L | 1 | L | 4,705 | 941 | -0.0408 | 0.0144 | 0.005 | 0.0160 | 0.011 | 0.0168 | (no prior) | n/a (no P1 prior) |
| post | outcome=L | 7 | S | 4,675 | 935 | 0.0713 | 0.0219 | 0.001 | 0.0252 | 0.005 | 0.0270 | + | MATCH (p<.05, DK) |
| post | outcome=L | 7 | D | 4,675 | 935 | -0.0167 | 0.0057 | 0.003 | 0.0083 | 0.045 | 0.0111 | (no prior) | n/a (no P1 prior) |
| post | outcome=L | 7 | L | 4,675 | 935 | -0.0717 | 0.0157 | <0.001 | 0.0175 | <0.001 | 0.0223 | (no prior) | n/a (no P1 prior) |
| post | outcome=L | 14 | S | 4,640 | 928 | 0.0879 | 0.0261 | <0.001 | 0.0352 | 0.013 | 0.0391 | + | MATCH (p<.05, DK) |
| post | outcome=L | 14 | D | 4,640 | 928 | -0.0098 | 0.0062 | 0.113 | 0.0105 | 0.352 | 0.0131 | (no prior) | n/a (no P1 prior) |
| post | outcome=L | 14 | L | 4,640 | 928 | -0.0950 | 0.0162 | <0.001 | 0.0223 | <0.001 | 0.0245 | (no prior) | n/a (no P1 prior) |
| post | outcome=L | 30 | S | 4,560 | 912 | 0.1585 | 0.0243 | <0.001 | 0.0593 | 0.008 | 0.0619 | + | MATCH (p<.05, DK) |
| post | outcome=L | 30 | D | 4,560 | 912 | -0.0026 | 0.0073 | 0.724 | 0.0172 | 0.881 | 0.0174 | (no prior) | n/a (no P1 prior) |
| post | outcome=L | 30 | L | 4,560 | 912 | -0.1420 | 0.0131 | <0.001 | 0.0373 | <0.001 | 0.0383 | (no prior) | n/a (no P1 prior) |
| post | outcome=D | 1 | L | 4,705 | 941 | -0.0618 | 0.0166 | <0.001 | 0.0194 | 0.002 | 0.0386 | - | MATCH (p<.05, DK) |
| post | outcome=D | 1 | S | 4,705 | 941 | -0.0463 | 0.0304 | 0.127 | 0.0275 | 0.092 | 0.0298 | (no prior) | n/a (no P1 prior) |
| post | outcome=D | 1 | D | 4,705 | 941 | -0.4359 | 0.0202 | <0.001 | 0.0243 | <0.001 | 0.0372 | (no prior) | n/a (no P1 prior) |
| post | outcome=D | 7 | L | 4,675 | 935 | -0.0717 | 0.0178 | <0.001 | 0.0292 | 0.014 | 0.0400 | - | MATCH (p<.05, DK) |
| post | outcome=D | 7 | S | 4,675 | 935 | -0.0703 | 0.0332 | 0.034 | 0.0395 | 0.075 | 0.0494 | (no prior) | n/a (no P1 prior) |
| post | outcome=D | 7 | D | 4,675 | 935 | -0.5084 | 0.0206 | <0.001 | 0.0288 | <0.001 | 0.0382 | (no prior) | n/a (no P1 prior) |
| post | outcome=D | 14 | L | 4,640 | 928 | -0.1026 | 0.0181 | <0.001 | 0.0385 | 0.008 | 0.0523 | - | MATCH (p<.05, DK) |
| post | outcome=D | 14 | S | 4,640 | 928 | -0.0075 | 0.0310 | 0.809 | 0.0511 | 0.883 | 0.0626 | (no prior) | n/a (no P1 prior) |
| post | outcome=D | 14 | D | 4,640 | 928 | -0.5895 | 0.0199 | <0.001 | 0.0330 | <0.001 | 0.0395 | (no prior) | n/a (no P1 prior) |
| post | outcome=D | 30 | L | 4,560 | 912 | -0.1376 | 0.0170 | <0.001 | 0.0418 | 0.001 | 0.0380 | - | MATCH (p<.05, DK) |
| post | outcome=D | 30 | S | 4,560 | 912 | -0.0387 | 0.0360 | 0.282 | 0.0706 | 0.584 | 0.0609 | (no prior) | n/a (no P1 prior) |
| post | outcome=D | 30 | D | 4,560 | 912 | -0.6606 | 0.0193 | <0.001 | 0.0335 | <0.001 | 0.0355 | (no prior) | n/a (no P1 prior) |

