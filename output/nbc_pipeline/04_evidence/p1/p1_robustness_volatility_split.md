# P1 robustness check: volatility_split

Split at the sample median of a trailing 30-day rolling std. dev. of WETH daily log returns (calm vs high volatility regime; 30-day window winsorized at +-50%/day to exclude 2 known price-feed glitch-days in-sample from the rolling-vol construction). Same system/inference as headline.

## Sample
| Sample | N rows | Tokens | First date | Last date |
| --- | --- | --- | --- | --- |
| volatility=calm | 4705 | 5 | 2021-08-26 | 2026-06-30 |
|   token=DAI | 941 | 1 | 2021-08-26 | 2026-06-30 |
|   token=USDC | 941 | 1 | 2021-08-26 | 2026-06-30 |
|   token=USDT | 941 | 1 | 2021-08-26 | 2026-06-30 |
|   token=WBTC | 941 | 1 | 2021-08-26 | 2026-06-30 |
|   token=WETH | 941 | 1 | 2021-08-26 | 2026-06-30 |
| volatility=high | 4710 | 5 | 2021-05-05 | 2026-04-10 |
|   token=DAI | 942 | 1 | 2021-05-05 | 2026-04-10 |
|   token=USDC | 942 | 1 | 2021-05-05 | 2026-04-10 |
|   token=USDT | 942 | 1 | 2021-05-05 | 2026-04-10 |
|   token=WBTC | 942 | 1 | 2021-05-05 | 2026-04-10 |
|   token=WETH | 942 | 1 | 2021-05-05 | 2026-04-10 |

## Results
| Volatility regime | Equation | Horizon (days) | Regressor | N | Date clusters | Beta | SE (cluster-by-date) | p (cluster-by-date) | SE (Driscoll-Kraay) | p (Driscoll-Kraay) | SE (month block bootstrap) | Predicted sign (P1) | Sign check |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| calm | outcome=S | 1 | L | 4,700 | 940 | 0.0250 | 0.0028 | <0.001 | 0.0024 | <0.001 | 0.0034 | + | MATCH (p<.05, DK) |
| calm | outcome=S | 1 | D | 4,700 | 940 | -0.0054 | 0.0043 | 0.212 | 0.0049 | 0.271 | 0.0069 | - | sign matches but not sig. (DK p=0.271) |
| calm | outcome=S | 1 | S | 4,700 | 940 | -0.4039 | 0.0266 | <0.001 | 0.0279 | <0.001 | 0.0324 | (no prior) | n/a (no P1 prior) |
| calm | outcome=S | 7 | L | 4,670 | 934 | 0.0335 | 0.0029 | <0.001 | 0.0037 | <0.001 | 0.0044 | + | MATCH (p<.05, DK) |
| calm | outcome=S | 7 | D | 4,670 | 934 | -0.0082 | 0.0048 | 0.093 | 0.0066 | 0.216 | 0.0083 | - | sign matches but not sig. (DK p=0.216) |
| calm | outcome=S | 7 | S | 4,670 | 934 | -0.5185 | 0.0279 | <0.001 | 0.0314 | <0.001 | 0.0393 | (no prior) | n/a (no P1 prior) |
| calm | outcome=S | 14 | L | 4,635 | 927 | 0.0318 | 0.0027 | <0.001 | 0.0036 | <0.001 | 0.0044 | + | MATCH (p<.05, DK) |
| calm | outcome=S | 14 | D | 4,635 | 927 | -0.0152 | 0.0047 | 0.001 | 0.0077 | 0.047 | 0.0089 | - | MATCH (p<.05, DK) |
| calm | outcome=S | 14 | S | 4,635 | 927 | -0.5330 | 0.0242 | <0.001 | 0.0323 | <0.001 | 0.0371 | (no prior) | n/a (no P1 prior) |
| calm | outcome=S | 30 | L | 4,555 | 911 | 0.0280 | 0.0028 | <0.001 | 0.0051 | <0.001 | 0.0060 | + | MATCH (p<.05, DK) |
| calm | outcome=S | 30 | D | 4,555 | 911 | -0.0102 | 0.0056 | 0.071 | 0.0088 | 0.246 | 0.0100 | - | sign matches but not sig. (DK p=0.246) |
| calm | outcome=S | 30 | S | 4,555 | 911 | -0.6276 | 0.0228 | <0.001 | 0.0396 | <0.001 | 0.0390 | (no prior) | n/a (no P1 prior) |
| calm | outcome=L | 1 | S | 4,700 | 940 | 0.0237 | 0.0170 | 0.163 | 0.0175 | 0.176 | 0.0169 | + | sign matches but not sig. (DK p=0.176) |
| calm | outcome=L | 1 | D | 4,700 | 940 | 0.0006 | 0.0044 | 0.899 | 0.0036 | 0.875 | 0.0037 | (no prior) | n/a (no P1 prior) |
| calm | outcome=L | 1 | L | 4,700 | 940 | -0.0154 | 0.0063 | 0.014 | 0.0064 | 0.016 | 0.0067 | (no prior) | n/a (no P1 prior) |
| calm | outcome=L | 7 | S | 4,670 | 934 | 0.0471 | 0.0205 | 0.022 | 0.0234 | 0.045 | 0.0212 | + | MATCH (p<.05, DK) |
| calm | outcome=L | 7 | D | 4,670 | 934 | -0.0168 | 0.0075 | 0.026 | 0.0106 | 0.112 | 0.0105 | (no prior) | n/a (no P1 prior) |
| calm | outcome=L | 7 | L | 4,670 | 934 | -0.0339 | 0.0089 | <0.001 | 0.0158 | 0.032 | 0.0178 | (no prior) | n/a (no P1 prior) |
| calm | outcome=L | 14 | S | 4,635 | 927 | 0.0739 | 0.0257 | 0.004 | 0.0335 | 0.028 | 0.0320 | + | MATCH (p<.05, DK) |
| calm | outcome=L | 14 | D | 4,635 | 927 | -0.0156 | 0.0092 | 0.090 | 0.0154 | 0.311 | 0.0173 | (no prior) | n/a (no P1 prior) |
| calm | outcome=L | 14 | L | 4,635 | 927 | -0.0327 | 0.0112 | 0.004 | 0.0268 | 0.222 | 0.0249 | (no prior) | n/a (no P1 prior) |
| calm | outcome=L | 30 | S | 4,555 | 911 | 0.1173 | 0.0204 | <0.001 | 0.0399 | 0.003 | 0.0412 | + | MATCH (p<.05, DK) |
| calm | outcome=L | 30 | D | 4,555 | 911 | -0.0206 | 0.0109 | 0.060 | 0.0265 | 0.437 | 0.0280 | (no prior) | n/a (no P1 prior) |
| calm | outcome=L | 30 | L | 4,555 | 911 | -0.0157 | 0.0112 | 0.162 | 0.0385 | 0.683 | 0.0381 | (no prior) | n/a (no P1 prior) |
| calm | outcome=D | 1 | L | 4,700 | 940 | 0.0071 | 0.0095 | 0.454 | 0.0086 | 0.409 | 0.0121 | - | WRONG SIGN (predicted -, got +) |
| calm | outcome=D | 1 | S | 4,700 | 940 | -0.0513 | 0.0227 | 0.024 | 0.0224 | 0.022 | 0.0306 | (no prior) | n/a (no P1 prior) |
| calm | outcome=D | 1 | D | 4,700 | 940 | -0.4379 | 0.0227 | <0.001 | 0.0288 | <0.001 | 0.0423 | (no prior) | n/a (no P1 prior) |
| calm | outcome=D | 7 | L | 4,670 | 934 | 0.0220 | 0.0100 | 0.028 | 0.0156 | 0.159 | 0.0191 | - | WRONG SIGN (predicted -, got +) |
| calm | outcome=D | 7 | S | 4,670 | 934 | -0.0812 | 0.0229 | <0.001 | 0.0329 | 0.014 | 0.0401 | (no prior) | n/a (no P1 prior) |
| calm | outcome=D | 7 | D | 4,670 | 934 | -0.5546 | 0.0235 | <0.001 | 0.0359 | <0.001 | 0.0514 | (no prior) | n/a (no P1 prior) |
| calm | outcome=D | 14 | L | 4,635 | 927 | 0.0232 | 0.0110 | 0.035 | 0.0216 | 0.282 | 0.0232 | - | WRONG SIGN (predicted -, got +) |
| calm | outcome=D | 14 | S | 4,635 | 927 | -0.0556 | 0.0251 | 0.027 | 0.0429 | 0.195 | 0.0472 | (no prior) | n/a (no P1 prior) |
| calm | outcome=D | 14 | D | 4,635 | 927 | -0.6445 | 0.0240 | <0.001 | 0.0467 | <0.001 | 0.0530 | (no prior) | n/a (no P1 prior) |
| calm | outcome=D | 30 | L | 4,555 | 911 | 0.0346 | 0.0117 | 0.003 | 0.0308 | 0.262 | 0.0323 | - | WRONG SIGN (predicted -, got +) |
| calm | outcome=D | 30 | S | 4,555 | 911 | -0.1223 | 0.0270 | <0.001 | 0.0618 | 0.048 | 0.0633 | (no prior) | n/a (no P1 prior) |
| calm | outcome=D | 30 | D | 4,555 | 911 | -0.7318 | 0.0223 | <0.001 | 0.0522 | <0.001 | 0.0540 | (no prior) | n/a (no P1 prior) |
| high | outcome=S | 1 | L | 4,710 | 942 | 0.0200 | 0.0018 | <0.001 | 0.0019 | <0.001 | 0.0029 | + | MATCH (p<.05, DK) |
| high | outcome=S | 1 | D | 4,710 | 942 | -0.0067 | 0.0056 | 0.230 | 0.0056 | 0.233 | 0.0074 | - | sign matches but not sig. (DK p=0.233) |
| high | outcome=S | 1 | S | 4,710 | 942 | -0.3957 | 0.0248 | <0.001 | 0.0263 | <0.001 | 0.0314 | (no prior) | n/a (no P1 prior) |
| high | outcome=S | 7 | L | 4,710 | 942 | 0.0212 | 0.0019 | <0.001 | 0.0028 | <0.001 | 0.0031 | + | MATCH (p<.05, DK) |
| high | outcome=S | 7 | D | 4,710 | 942 | -0.0032 | 0.0054 | 0.557 | 0.0070 | 0.650 | 0.0101 | - | sign matches but not sig. (DK p=0.650) |
| high | outcome=S | 7 | S | 4,710 | 942 | -0.5237 | 0.0238 | <0.001 | 0.0287 | <0.001 | 0.0307 | (no prior) | n/a (no P1 prior) |
| high | outcome=S | 14 | L | 4,710 | 942 | 0.0236 | 0.0022 | <0.001 | 0.0038 | <0.001 | 0.0038 | + | MATCH (p<.05, DK) |
| high | outcome=S | 14 | D | 4,710 | 942 | -0.0083 | 0.0056 | 0.143 | 0.0095 | 0.387 | 0.0109 | - | sign matches but not sig. (DK p=0.387) |
| high | outcome=S | 14 | S | 4,710 | 942 | -0.6215 | 0.0262 | <0.001 | 0.0441 | <0.001 | 0.0507 | (no prior) | n/a (no P1 prior) |
| high | outcome=S | 30 | L | 4,710 | 942 | 0.0257 | 0.0019 | <0.001 | 0.0040 | <0.001 | 0.0047 | + | MATCH (p<.05, DK) |
| high | outcome=S | 30 | D | 4,710 | 942 | -0.0153 | 0.0060 | 0.010 | 0.0117 | 0.188 | 0.0126 | - | sign matches but not sig. (DK p=0.188) |
| high | outcome=S | 30 | S | 4,710 | 942 | -0.6655 | 0.0220 | <0.001 | 0.0367 | <0.001 | 0.0383 | (no prior) | n/a (no P1 prior) |
| high | outcome=L | 1 | S | 4,710 | 942 | 0.0153 | 0.0109 | 0.160 | 0.0100 | 0.125 | 0.0118 | + | sign matches but not sig. (DK p=0.125) |
| high | outcome=L | 1 | D | 4,710 | 942 | -0.0034 | 0.0037 | 0.364 | 0.0035 | 0.333 | 0.0032 | (no prior) | n/a (no P1 prior) |
| high | outcome=L | 1 | L | 4,710 | 942 | -0.0067 | 0.0030 | 0.026 | 0.0034 | 0.050 | 0.0040 | (no prior) | n/a (no P1 prior) |
| high | outcome=L | 7 | S | 4,710 | 942 | 0.0323 | 0.0145 | 0.026 | 0.0198 | 0.103 | 0.0159 | + | sign matches but not sig. (DK p=0.103) |
| high | outcome=L | 7 | D | 4,710 | 942 | -0.0095 | 0.0067 | 0.157 | 0.0093 | 0.308 | 0.0122 | (no prior) | n/a (no P1 prior) |
| high | outcome=L | 7 | L | 4,710 | 942 | -0.0144 | 0.0044 | 0.001 | 0.0085 | 0.090 | 0.0126 | (no prior) | n/a (no P1 prior) |
| high | outcome=L | 14 | S | 4,710 | 942 | 0.0342 | 0.0204 | 0.094 | 0.0416 | 0.411 | 0.0504 | + | sign matches but not sig. (DK p=0.411) |
| high | outcome=L | 14 | D | 4,710 | 942 | -0.0280 | 0.0096 | 0.003 | 0.0199 | 0.159 | 0.0237 | (no prior) | n/a (no P1 prior) |
| high | outcome=L | 14 | L | 4,710 | 942 | -0.0277 | 0.0058 | <0.001 | 0.0167 | 0.098 | 0.0204 | (no prior) | n/a (no P1 prior) |
| high | outcome=L | 30 | S | 4,710 | 942 | 0.0777 | 0.0239 | 0.001 | 0.0511 | 0.129 | 0.0592 | + | sign matches but not sig. (DK p=0.129) |
| high | outcome=L | 30 | D | 4,710 | 942 | -0.0666 | 0.0140 | <0.001 | 0.0366 | 0.069 | 0.0352 | (no prior) | n/a (no P1 prior) |
| high | outcome=L | 30 | L | 4,710 | 942 | -0.0565 | 0.0077 | <0.001 | 0.0334 | 0.091 | 0.0297 | (no prior) | n/a (no P1 prior) |
| high | outcome=D | 1 | L | 4,710 | 942 | 0.0117 | 0.0073 | 0.107 | 0.0072 | 0.106 | 0.0107 | - | WRONG SIGN (predicted -, got +) |
| high | outcome=D | 1 | S | 4,710 | 942 | -0.0230 | 0.0224 | 0.305 | 0.0236 | 0.330 | 0.0293 | (no prior) | n/a (no P1 prior) |
| high | outcome=D | 1 | D | 4,710 | 942 | -0.5522 | 0.0227 | <0.001 | 0.0270 | <0.001 | 0.0344 | (no prior) | n/a (no P1 prior) |
| high | outcome=D | 7 | L | 4,710 | 942 | 0.0122 | 0.0075 | 0.105 | 0.0105 | 0.243 | 0.0149 | - | WRONG SIGN (predicted -, got +) |
| high | outcome=D | 7 | S | 4,710 | 942 | -0.0225 | 0.0268 | 0.402 | 0.0341 | 0.511 | 0.0414 | (no prior) | n/a (no P1 prior) |
| high | outcome=D | 7 | D | 4,710 | 942 | -0.6504 | 0.0225 | <0.001 | 0.0324 | <0.001 | 0.0453 | (no prior) | n/a (no P1 prior) |
| high | outcome=D | 14 | L | 4,710 | 942 | 0.0137 | 0.0079 | 0.084 | 0.0137 | 0.316 | 0.0177 | - | WRONG SIGN (predicted -, got +) |
| high | outcome=D | 14 | S | 4,710 | 942 | 0.0034 | 0.0249 | 0.891 | 0.0449 | 0.940 | 0.0526 | (no prior) | n/a (no P1 prior) |
| high | outcome=D | 14 | D | 4,710 | 942 | -0.7203 | 0.0218 | <0.001 | 0.0380 | <0.001 | 0.0496 | (no prior) | n/a (no P1 prior) |
| high | outcome=D | 30 | L | 4,710 | 942 | 0.0186 | 0.0074 | 0.012 | 0.0151 | 0.219 | 0.0169 | - | WRONG SIGN (predicted -, got +) |
| high | outcome=D | 30 | S | 4,710 | 942 | 0.0107 | 0.0290 | 0.712 | 0.0596 | 0.858 | 0.0533 | (no prior) | n/a (no P1 prior) |
| high | outcome=D | 30 | D | 4,710 | 942 | -0.6927 | 0.0219 | <0.001 | 0.0444 | <0.001 | 0.0433 | (no prior) | n/a (no P1 prior) |

