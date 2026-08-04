# P1 robustness check: altmeasure

Four alternative-measure variants of the headline system: (a) lp_concentration (share) in place of log_vehicle_linked_liquidity (level) as the depth measure L; (b) winsorized mean in place of median DirectCostAdvantage; (c)/(d) $1k / $100k common-support windows in place of the headline's $10k window. Same 3-equation system, same 3 inference methods, run separately for each variant.

## Sample
| Variant | N core rows |
| --- | --- |
| alt_depth_lp_concentration | 9415 |
| alt_D_winsor_mean | 9415 |
| alt_D_q1k | 9415 |
| alt_D_q100k | 9415 |

## Results
| Variant | N core rows | Equation | Horizon (days) | Regressor | N | Date clusters | Beta | SE (cluster-by-date) | p (cluster-by-date) | SE (Driscoll-Kraay) | p (Driscoll-Kraay) | SE (month block bootstrap) | Predicted sign (P1) | Sign check |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| alt_depth_lp_concentration | 9415 | outcome=S | 1 | L | 9,410 | 1,882 | 0.2044 | 0.0185 | <0.001 | 0.0175 | <0.001 | 0.0285 | + | MATCH (p<.05, DK) |
| alt_depth_lp_concentration | 9415 | outcome=S | 1 | D | 9,410 | 1,882 | -0.0058 | 0.0035 | 0.099 | 0.0037 | 0.118 | 0.0052 | - | sign matches but not sig. (DK p=0.118) |
| alt_depth_lp_concentration | 9415 | outcome=S | 1 | S | 9,410 | 1,882 | -0.4141 | 0.0185 | <0.001 | 0.0201 | <0.001 | 0.0264 | (no prior) | n/a (no P1 prior) |
| alt_depth_lp_concentration | 9415 | outcome=S | 7 | L | 9,380 | 1,876 | 0.2272 | 0.0197 | <0.001 | 0.0283 | <0.001 | 0.0352 | + | MATCH (p<.05, DK) |
| alt_depth_lp_concentration | 9415 | outcome=S | 7 | D | 9,380 | 1,876 | -0.0051 | 0.0036 | 0.159 | 0.0050 | 0.304 | 0.0071 | - | sign matches but not sig. (DK p=0.304) |
| alt_depth_lp_concentration | 9415 | outcome=S | 7 | S | 9,380 | 1,876 | -0.5363 | 0.0186 | <0.001 | 0.0226 | <0.001 | 0.0300 | (no prior) | n/a (no P1 prior) |
| alt_depth_lp_concentration | 9415 | outcome=S | 14 | L | 9,345 | 1,869 | 0.2282 | 0.0202 | <0.001 | 0.0358 | <0.001 | 0.0430 | + | MATCH (p<.05, DK) |
| alt_depth_lp_concentration | 9415 | outcome=S | 14 | D | 9,345 | 1,869 | -0.0114 | 0.0038 | 0.002 | 0.0068 | 0.092 | 0.0089 | - | sign matches but not sig. (DK p=0.092) |
| alt_depth_lp_concentration | 9415 | outcome=S | 14 | S | 9,345 | 1,869 | -0.5932 | 0.0181 | <0.001 | 0.0293 | <0.001 | 0.0374 | (no prior) | n/a (no P1 prior) |
| alt_depth_lp_concentration | 9415 | outcome=S | 30 | L | 9,265 | 1,853 | 0.2225 | 0.0200 | <0.001 | 0.0462 | <0.001 | 0.0526 | + | MATCH (p<.05, DK) |
| alt_depth_lp_concentration | 9415 | outcome=S | 30 | D | 9,265 | 1,853 | -0.0122 | 0.0041 | 0.003 | 0.0089 | 0.170 | 0.0089 | - | sign matches but not sig. (DK p=0.170) |
| alt_depth_lp_concentration | 9415 | outcome=S | 30 | S | 9,265 | 1,853 | -0.6634 | 0.0162 | <0.001 | 0.0307 | <0.001 | 0.0317 | (no prior) | n/a (no P1 prior) |
| alt_depth_lp_concentration | 9415 | outcome=L | 1 | S | 9,410 | 1,882 | 0.0076 | 0.0029 | 0.010 | 0.0032 | 0.020 | 0.0035 | + | MATCH (p<.05, DK) |
| alt_depth_lp_concentration | 9415 | outcome=L | 1 | D | 9,410 | 1,882 | 0.0003 | 0.0004 | 0.533 | 0.0004 | 0.485 | 0.0004 | (no prior) | n/a (no P1 prior) |
| alt_depth_lp_concentration | 9415 | outcome=L | 1 | L | 9,410 | 1,882 | -0.0191 | 0.0067 | 0.004 | 0.0073 | 0.009 | 0.0087 | (no prior) | n/a (no P1 prior) |
| alt_depth_lp_concentration | 9415 | outcome=L | 7 | S | 9,380 | 1,876 | 0.0141 | 0.0036 | <0.001 | 0.0043 | 0.001 | 0.0042 | + | MATCH (p<.05, DK) |
| alt_depth_lp_concentration | 9415 | outcome=L | 7 | D | 9,380 | 1,876 | -0.0011 | 0.0007 | 0.089 | 0.0009 | 0.215 | 0.0009 | (no prior) | n/a (no P1 prior) |
| alt_depth_lp_concentration | 9415 | outcome=L | 7 | L | 9,380 | 1,876 | -0.0399 | 0.0083 | <0.001 | 0.0127 | 0.002 | 0.0163 | (no prior) | n/a (no P1 prior) |
| alt_depth_lp_concentration | 9415 | outcome=L | 14 | S | 9,345 | 1,869 | 0.0181 | 0.0045 | <0.001 | 0.0071 | 0.011 | 0.0075 | + | MATCH (p<.05, DK) |
| alt_depth_lp_concentration | 9415 | outcome=L | 14 | D | 9,345 | 1,869 | -0.0020 | 0.0009 | 0.019 | 0.0015 | 0.184 | 0.0016 | (no prior) | n/a (no P1 prior) |
| alt_depth_lp_concentration | 9415 | outcome=L | 14 | L | 9,345 | 1,869 | -0.0602 | 0.0096 | <0.001 | 0.0215 | 0.005 | 0.0237 | (no prior) | n/a (no P1 prior) |
| alt_depth_lp_concentration | 9415 | outcome=L | 30 | S | 9,265 | 1,853 | 0.0315 | 0.0045 | <0.001 | 0.0092 | <0.001 | 0.0091 | + | MATCH (p<.05, DK) |
| alt_depth_lp_concentration | 9415 | outcome=L | 30 | D | 9,265 | 1,853 | -0.0042 | 0.0011 | <0.001 | 0.0028 | 0.133 | 0.0028 | (no prior) | n/a (no P1 prior) |
| alt_depth_lp_concentration | 9415 | outcome=L | 30 | L | 9,265 | 1,853 | -0.0922 | 0.0094 | <0.001 | 0.0367 | 0.012 | 0.0358 | (no prior) | n/a (no P1 prior) |
| alt_depth_lp_concentration | 9415 | outcome=D | 1 | L | 9,410 | 1,882 | 0.0517 | 0.0248 | 0.037 | 0.0207 | 0.013 | 0.0274 | - | WRONG SIGN (predicted -, got +) |
| alt_depth_lp_concentration | 9415 | outcome=D | 1 | S | 9,410 | 1,882 | -0.0386 | 0.0165 | 0.020 | 0.0163 | 0.018 | 0.0204 | (no prior) | n/a (no P1 prior) |
| alt_depth_lp_concentration | 9415 | outcome=D | 1 | D | 9,410 | 1,882 | -0.4916 | 0.0162 | <0.001 | 0.0208 | <0.001 | 0.0326 | (no prior) | n/a (no P1 prior) |
| alt_depth_lp_concentration | 9415 | outcome=D | 7 | L | 9,380 | 1,876 | 0.0781 | 0.0263 | 0.003 | 0.0339 | 0.021 | 0.0337 | - | WRONG SIGN (predicted -, got +) |
| alt_depth_lp_concentration | 9415 | outcome=D | 7 | S | 9,380 | 1,876 | -0.0530 | 0.0186 | 0.004 | 0.0252 | 0.035 | 0.0315 | (no prior) | n/a (no P1 prior) |
| alt_depth_lp_concentration | 9415 | outcome=D | 7 | D | 9,380 | 1,876 | -0.5991 | 0.0163 | <0.001 | 0.0247 | <0.001 | 0.0384 | (no prior) | n/a (no P1 prior) |
| alt_depth_lp_concentration | 9415 | outcome=D | 14 | L | 9,345 | 1,869 | 0.0670 | 0.0273 | 0.014 | 0.0426 | 0.116 | 0.0468 | - | WRONG SIGN (predicted -, got +) |
| alt_depth_lp_concentration | 9415 | outcome=D | 14 | S | 9,345 | 1,869 | -0.0247 | 0.0184 | 0.180 | 0.0331 | 0.457 | 0.0377 | (no prior) | n/a (no P1 prior) |
| alt_depth_lp_concentration | 9415 | outcome=D | 14 | D | 9,345 | 1,869 | -0.6801 | 0.0161 | <0.001 | 0.0300 | <0.001 | 0.0370 | (no prior) | n/a (no P1 prior) |
| alt_depth_lp_concentration | 9415 | outcome=D | 30 | L | 9,265 | 1,853 | 0.0923 | 0.0261 | <0.001 | 0.0553 | 0.095 | 0.0613 | - | WRONG SIGN (predicted -, got +) |
| alt_depth_lp_concentration | 9415 | outcome=D | 30 | S | 9,265 | 1,853 | -0.0465 | 0.0206 | 0.024 | 0.0459 | 0.312 | 0.0431 | (no prior) | n/a (no P1 prior) |
| alt_depth_lp_concentration | 9415 | outcome=D | 30 | D | 9,265 | 1,853 | -0.7103 | 0.0156 | <0.001 | 0.0345 | <0.001 | 0.0345 | (no prior) | n/a (no P1 prior) |
| alt_D_winsor_mean | 9415 | outcome=S | 1 | L | 9,410 | 1,882 | 0.0236 | 0.0015 | <0.001 | 0.0016 | <0.001 | 0.0026 | + | MATCH (p<.05, DK) |
| alt_D_winsor_mean | 9415 | outcome=S | 1 | D | 9,410 | 1,882 | -0.0448 | 0.0084 | <0.001 | 0.0085 | <0.001 | 0.0129 | - | MATCH (p<.05, DK) |
| alt_D_winsor_mean | 9415 | outcome=S | 1 | S | 9,410 | 1,882 | -0.3971 | 0.0181 | <0.001 | 0.0194 | <0.001 | 0.0253 | (no prior) | n/a (no P1 prior) |
| alt_D_winsor_mean | 9415 | outcome=S | 7 | L | 9,380 | 1,876 | 0.0276 | 0.0017 | <0.001 | 0.0024 | <0.001 | 0.0032 | + | MATCH (p<.05, DK) |
| alt_D_winsor_mean | 9415 | outcome=S | 7 | D | 9,380 | 1,876 | -0.0495 | 0.0094 | <0.001 | 0.0136 | <0.001 | 0.0182 | - | MATCH (p<.05, DK) |
| alt_D_winsor_mean | 9415 | outcome=S | 7 | S | 9,380 | 1,876 | -0.5190 | 0.0181 | <0.001 | 0.0215 | <0.001 | 0.0271 | (no prior) | n/a (no P1 prior) |
| alt_D_winsor_mean | 9415 | outcome=S | 14 | L | 9,345 | 1,869 | 0.0284 | 0.0018 | <0.001 | 0.0030 | <0.001 | 0.0034 | + | MATCH (p<.05, DK) |
| alt_D_winsor_mean | 9415 | outcome=S | 14 | D | 9,345 | 1,869 | -0.0532 | 0.0096 | <0.001 | 0.0170 | 0.002 | 0.0208 | - | MATCH (p<.05, DK) |
| alt_D_winsor_mean | 9415 | outcome=S | 14 | S | 9,345 | 1,869 | -0.5768 | 0.0177 | <0.001 | 0.0278 | <0.001 | 0.0338 | (no prior) | n/a (no P1 prior) |
| alt_D_winsor_mean | 9415 | outcome=S | 30 | L | 9,265 | 1,853 | 0.0290 | 0.0017 | <0.001 | 0.0038 | <0.001 | 0.0041 | + | MATCH (p<.05, DK) |
| alt_D_winsor_mean | 9415 | outcome=S | 30 | D | 9,265 | 1,853 | -0.0753 | 0.0102 | <0.001 | 0.0238 | 0.002 | 0.0238 | - | MATCH (p<.05, DK) |
| alt_D_winsor_mean | 9415 | outcome=S | 30 | S | 9,265 | 1,853 | -0.6506 | 0.0157 | <0.001 | 0.0278 | <0.001 | 0.0271 | (no prior) | n/a (no P1 prior) |
| alt_D_winsor_mean | 9415 | outcome=L | 1 | S | 9,410 | 1,882 | 0.0194 | 0.0092 | 0.034 | 0.0099 | 0.051 | 0.0100 | + | sign matches but not sig. (DK p=0.051) |
| alt_D_winsor_mean | 9415 | outcome=L | 1 | D | 9,410 | 1,882 | 0.0032 | 0.0068 | 0.634 | 0.0062 | 0.605 | 0.0062 | (no prior) | n/a (no P1 prior) |
| alt_D_winsor_mean | 9415 | outcome=L | 1 | L | 9,410 | 1,882 | -0.0091 | 0.0029 | 0.002 | 0.0032 | 0.004 | 0.0033 | (no prior) | n/a (no P1 prior) |
| alt_D_winsor_mean | 9415 | outcome=L | 7 | S | 9,380 | 1,876 | 0.0369 | 0.0114 | 0.001 | 0.0148 | 0.013 | 0.0129 | + | MATCH (p<.05, DK) |
| alt_D_winsor_mean | 9415 | outcome=L | 7 | D | 9,380 | 1,876 | -0.0100 | 0.0087 | 0.255 | 0.0127 | 0.434 | 0.0132 | (no prior) | n/a (no P1 prior) |
| alt_D_winsor_mean | 9415 | outcome=L | 7 | L | 9,380 | 1,876 | -0.0185 | 0.0042 | <0.001 | 0.0077 | 0.017 | 0.0094 | (no prior) | n/a (no P1 prior) |
| alt_D_winsor_mean | 9415 | outcome=L | 14 | S | 9,345 | 1,869 | 0.0475 | 0.0145 | 0.001 | 0.0236 | 0.044 | 0.0258 | + | MATCH (p<.05, DK) |
| alt_D_winsor_mean | 9415 | outcome=L | 14 | D | 9,345 | 1,869 | -0.0129 | 0.0123 | 0.297 | 0.0229 | 0.574 | 0.0240 | (no prior) | n/a (no P1 prior) |
| alt_D_winsor_mean | 9415 | outcome=L | 14 | L | 9,345 | 1,869 | -0.0268 | 0.0053 | <0.001 | 0.0145 | 0.064 | 0.0151 | (no prior) | n/a (no P1 prior) |
| alt_D_winsor_mean | 9415 | outcome=L | 30 | S | 9,265 | 1,853 | 0.0840 | 0.0154 | <0.001 | 0.0334 | 0.012 | 0.0336 | + | MATCH (p<.05, DK) |
| alt_D_winsor_mean | 9415 | outcome=L | 30 | D | 9,265 | 1,853 | -0.0168 | 0.0130 | 0.196 | 0.0339 | 0.620 | 0.0330 | (no prior) | n/a (no P1 prior) |
| alt_D_winsor_mean | 9415 | outcome=L | 30 | L | 9,265 | 1,853 | -0.0426 | 0.0065 | <0.001 | 0.0270 | 0.115 | 0.0259 | (no prior) | n/a (no P1 prior) |
| alt_D_winsor_mean | 9415 | outcome=D | 1 | L | 9,410 | 1,882 | 0.0133 | 0.0025 | <0.001 | 0.0022 | <0.001 | 0.0034 | - | WRONG SIGN (predicted -, got +) |
| alt_D_winsor_mean | 9415 | outcome=D | 1 | S | 9,410 | 1,882 | -0.0650 | 0.0125 | <0.001 | 0.0135 | <0.001 | 0.0193 | (no prior) | n/a (no P1 prior) |
| alt_D_winsor_mean | 9415 | outcome=D | 1 | D | 9,410 | 1,882 | -0.4060 | 0.0103 | <0.001 | 0.0123 | <0.001 | 0.0192 | (no prior) | n/a (no P1 prior) |
| alt_D_winsor_mean | 9415 | outcome=D | 7 | L | 9,380 | 1,876 | 0.0195 | 0.0026 | <0.001 | 0.0039 | <0.001 | 0.0048 | - | WRONG SIGN (predicted -, got +) |
| alt_D_winsor_mean | 9415 | outcome=D | 7 | S | 9,380 | 1,876 | -0.0938 | 0.0143 | <0.001 | 0.0208 | <0.001 | 0.0260 | (no prior) | n/a (no P1 prior) |
| alt_D_winsor_mean | 9415 | outcome=D | 7 | D | 9,380 | 1,876 | -0.5363 | 0.0108 | <0.001 | 0.0169 | <0.001 | 0.0272 | (no prior) | n/a (no P1 prior) |
| alt_D_winsor_mean | 9415 | outcome=D | 14 | L | 9,345 | 1,869 | 0.0222 | 0.0027 | <0.001 | 0.0051 | <0.001 | 0.0052 | - | WRONG SIGN (predicted -, got +) |
| alt_D_winsor_mean | 9415 | outcome=D | 14 | S | 9,345 | 1,869 | -0.1014 | 0.0145 | <0.001 | 0.0241 | <0.001 | 0.0251 | (no prior) | n/a (no P1 prior) |
| alt_D_winsor_mean | 9415 | outcome=D | 14 | D | 9,345 | 1,869 | -0.5891 | 0.0111 | <0.001 | 0.0201 | <0.001 | 0.0242 | (no prior) | n/a (no P1 prior) |
| alt_D_winsor_mean | 9415 | outcome=D | 30 | L | 9,265 | 1,853 | 0.0286 | 0.0027 | <0.001 | 0.0066 | <0.001 | 0.0069 | - | WRONG SIGN (predicted -, got +) |
| alt_D_winsor_mean | 9415 | outcome=D | 30 | S | 9,265 | 1,853 | -0.1151 | 0.0150 | <0.001 | 0.0311 | <0.001 | 0.0301 | (no prior) | n/a (no P1 prior) |
| alt_D_winsor_mean | 9415 | outcome=D | 30 | D | 9,265 | 1,853 | -0.6443 | 0.0119 | <0.001 | 0.0280 | <0.001 | 0.0287 | (no prior) | n/a (no P1 prior) |
| alt_D_q1k | 9415 | outcome=S | 1 | L | 9,410 | 1,882 | 0.0224 | 0.0015 | <0.001 | 0.0015 | <0.001 | 0.0024 | + | MATCH (p<.05, DK) |
| alt_D_q1k | 9415 | outcome=S | 1 | D | 9,410 | 1,882 | -0.0171 | 0.0068 | 0.013 | 0.0072 | 0.018 | 0.0098 | - | MATCH (p<.05, DK) |
| alt_D_q1k | 9415 | outcome=S | 1 | S | 9,410 | 1,882 | -0.3905 | 0.0180 | <0.001 | 0.0192 | <0.001 | 0.0252 | (no prior) | n/a (no P1 prior) |
| alt_D_q1k | 9415 | outcome=S | 7 | L | 9,380 | 1,876 | 0.0261 | 0.0016 | <0.001 | 0.0023 | <0.001 | 0.0030 | + | MATCH (p<.05, DK) |
| alt_D_q1k | 9415 | outcome=S | 7 | D | 9,380 | 1,876 | -0.0108 | 0.0065 | 0.097 | 0.0081 | 0.185 | 0.0110 | - | sign matches but not sig. (DK p=0.185) |
| alt_D_q1k | 9415 | outcome=S | 7 | S | 9,380 | 1,876 | -0.5117 | 0.0180 | <0.001 | 0.0213 | <0.001 | 0.0274 | (no prior) | n/a (no P1 prior) |
| alt_D_q1k | 9415 | outcome=S | 14 | L | 9,345 | 1,869 | 0.0269 | 0.0017 | <0.001 | 0.0030 | <0.001 | 0.0032 | + | MATCH (p<.05, DK) |
| alt_D_q1k | 9415 | outcome=S | 14 | D | 9,345 | 1,869 | -0.0135 | 0.0070 | 0.053 | 0.0108 | 0.209 | 0.0148 | - | sign matches but not sig. (DK p=0.209) |
| alt_D_q1k | 9415 | outcome=S | 14 | S | 9,345 | 1,869 | -0.5690 | 0.0176 | <0.001 | 0.0279 | <0.001 | 0.0346 | (no prior) | n/a (no P1 prior) |
| alt_D_q1k | 9415 | outcome=S | 30 | L | 9,265 | 1,853 | 0.0269 | 0.0016 | <0.001 | 0.0036 | <0.001 | 0.0040 | + | MATCH (p<.05, DK) |
| alt_D_q1k | 9415 | outcome=S | 30 | D | 9,265 | 1,853 | -0.0136 | 0.0075 | 0.071 | 0.0128 | 0.287 | 0.0142 | - | sign matches but not sig. (DK p=0.287) |
| alt_D_q1k | 9415 | outcome=S | 30 | S | 9,265 | 1,853 | -0.6400 | 0.0157 | <0.001 | 0.0287 | <0.001 | 0.0285 | (no prior) | n/a (no P1 prior) |
| alt_D_q1k | 9415 | outcome=L | 1 | S | 9,410 | 1,882 | 0.0189 | 0.0091 | 0.037 | 0.0095 | 0.045 | 0.0093 | + | MATCH (p<.05, DK) |
| alt_D_q1k | 9415 | outcome=L | 1 | D | 9,410 | 1,882 | 0.0026 | 0.0057 | 0.648 | 0.0049 | 0.589 | 0.0071 | (no prior) | n/a (no P1 prior) |
| alt_D_q1k | 9415 | outcome=L | 1 | L | 9,410 | 1,882 | -0.0090 | 0.0029 | 0.002 | 0.0031 | 0.004 | 0.0033 | (no prior) | n/a (no P1 prior) |
| alt_D_q1k | 9415 | outcome=L | 7 | S | 9,380 | 1,876 | 0.0383 | 0.0114 | <0.001 | 0.0147 | 0.009 | 0.0131 | + | MATCH (p<.05, DK) |
| alt_D_q1k | 9415 | outcome=L | 7 | D | 9,380 | 1,876 | -0.0240 | 0.0154 | 0.120 | 0.0212 | 0.259 | 0.0195 | (no prior) | n/a (no P1 prior) |
| alt_D_q1k | 9415 | outcome=L | 7 | L | 9,380 | 1,876 | -0.0184 | 0.0042 | <0.001 | 0.0076 | 0.016 | 0.0093 | (no prior) | n/a (no P1 prior) |
| alt_D_q1k | 9415 | outcome=L | 14 | S | 9,345 | 1,869 | 0.0492 | 0.0148 | <0.001 | 0.0247 | 0.047 | 0.0278 | + | MATCH (p<.05, DK) |
| alt_D_q1k | 9415 | outcome=L | 14 | D | 9,345 | 1,869 | -0.0621 | 0.0205 | 0.002 | 0.0372 | 0.095 | 0.0424 | (no prior) | n/a (no P1 prior) |
| alt_D_q1k | 9415 | outcome=L | 14 | L | 9,345 | 1,869 | -0.0263 | 0.0053 | <0.001 | 0.0142 | 0.065 | 0.0147 | (no prior) | n/a (no P1 prior) |
| alt_D_q1k | 9415 | outcome=L | 30 | S | 9,265 | 1,853 | 0.0861 | 0.0154 | <0.001 | 0.0347 | 0.013 | 0.0353 | + | MATCH (p<.05, DK) |
| alt_D_q1k | 9415 | outcome=L | 30 | D | 9,265 | 1,853 | -0.1108 | 0.0254 | <0.001 | 0.0668 | 0.098 | 0.0633 | (no prior) | n/a (no P1 prior) |
| alt_D_q1k | 9415 | outcome=L | 30 | L | 9,265 | 1,853 | -0.0414 | 0.0064 | <0.001 | 0.0266 | 0.119 | 0.0255 | (no prior) | n/a (no P1 prior) |
| alt_D_q1k | 9415 | outcome=D | 1 | L | 9,410 | 1,882 | 0.0101 | 0.0030 | <0.001 | 0.0031 | 0.001 | 0.0044 | - | WRONG SIGN (predicted -, got +) |
| alt_D_q1k | 9415 | outcome=D | 1 | S | 9,410 | 1,882 | -0.0140 | 0.0055 | 0.012 | 0.0058 | 0.016 | 0.0077 | (no prior) | n/a (no P1 prior) |
| alt_D_q1k | 9415 | outcome=D | 1 | D | 9,410 | 1,882 | -0.6204 | 0.0378 | <0.001 | 0.0407 | <0.001 | 0.0565 | (no prior) | n/a (no P1 prior) |
| alt_D_q1k | 9415 | outcome=D | 7 | L | 9,380 | 1,876 | 0.0116 | 0.0030 | <0.001 | 0.0040 | 0.004 | 0.0046 | - | WRONG SIGN (predicted -, got +) |
| alt_D_q1k | 9415 | outcome=D | 7 | S | 9,380 | 1,876 | -0.0191 | 0.0054 | <0.001 | 0.0075 | 0.011 | 0.0093 | (no prior) | n/a (no P1 prior) |
| alt_D_q1k | 9415 | outcome=D | 7 | D | 9,380 | 1,876 | -0.6403 | 0.0362 | <0.001 | 0.0398 | <0.001 | 0.0338 | (no prior) | n/a (no P1 prior) |
| alt_D_q1k | 9415 | outcome=D | 14 | L | 9,345 | 1,869 | 0.0134 | 0.0030 | <0.001 | 0.0050 | 0.008 | 0.0057 | - | WRONG SIGN (predicted -, got +) |
| alt_D_q1k | 9415 | outcome=D | 14 | S | 9,345 | 1,869 | -0.0126 | 0.0061 | 0.037 | 0.0095 | 0.185 | 0.0105 | (no prior) | n/a (no P1 prior) |
| alt_D_q1k | 9415 | outcome=D | 14 | D | 9,345 | 1,869 | -0.7338 | 0.0308 | <0.001 | 0.0388 | <0.001 | 0.0396 | (no prior) | n/a (no P1 prior) |
| alt_D_q1k | 9415 | outcome=D | 30 | L | 9,265 | 1,853 | 0.0165 | 0.0032 | <0.001 | 0.0070 | 0.019 | 0.0073 | - | WRONG SIGN (predicted -, got +) |
| alt_D_q1k | 9415 | outcome=D | 30 | S | 9,265 | 1,853 | -0.0148 | 0.0062 | 0.018 | 0.0127 | 0.243 | 0.0122 | (no prior) | n/a (no P1 prior) |
| alt_D_q1k | 9415 | outcome=D | 30 | D | 9,265 | 1,853 | -0.7626 | 0.0318 | <0.001 | 0.0530 | <0.001 | 0.0540 | (no prior) | n/a (no P1 prior) |
| alt_D_q100k | 9415 | outcome=S | 1 | L | 9,410 | 1,882 | 0.0220 | 0.0015 | <0.001 | 0.0015 | <0.001 | 0.0025 | + | MATCH (p<.05, DK) |
| alt_D_q100k | 9415 | outcome=S | 1 | D | 9,410 | 1,882 | -0.0118 | 0.0027 | <0.001 | 0.0029 | <0.001 | 0.0047 | - | MATCH (p<.05, DK) |
| alt_D_q100k | 9415 | outcome=S | 1 | S | 9,410 | 1,882 | -0.3935 | 0.0181 | <0.001 | 0.0192 | <0.001 | 0.0251 | (no prior) | n/a (no P1 prior) |
| alt_D_q100k | 9415 | outcome=S | 7 | L | 9,380 | 1,876 | 0.0257 | 0.0016 | <0.001 | 0.0022 | <0.001 | 0.0030 | + | MATCH (p<.05, DK) |
| alt_D_q100k | 9415 | outcome=S | 7 | D | 9,380 | 1,876 | -0.0154 | 0.0031 | <0.001 | 0.0043 | <0.001 | 0.0059 | - | MATCH (p<.05, DK) |
| alt_D_q100k | 9415 | outcome=S | 7 | S | 9,380 | 1,876 | -0.5157 | 0.0180 | <0.001 | 0.0215 | <0.001 | 0.0276 | (no prior) | n/a (no P1 prior) |
| alt_D_q100k | 9415 | outcome=S | 14 | L | 9,345 | 1,869 | 0.0264 | 0.0017 | <0.001 | 0.0029 | <0.001 | 0.0033 | + | MATCH (p<.05, DK) |
| alt_D_q100k | 9415 | outcome=S | 14 | D | 9,345 | 1,869 | -0.0192 | 0.0032 | <0.001 | 0.0052 | <0.001 | 0.0066 | - | MATCH (p<.05, DK) |
| alt_D_q100k | 9415 | outcome=S | 14 | S | 9,345 | 1,869 | -0.5739 | 0.0177 | <0.001 | 0.0281 | <0.001 | 0.0349 | (no prior) | n/a (no P1 prior) |
| alt_D_q100k | 9415 | outcome=S | 30 | L | 9,265 | 1,853 | 0.0263 | 0.0016 | <0.001 | 0.0036 | <0.001 | 0.0039 | + | MATCH (p<.05, DK) |
| alt_D_q100k | 9415 | outcome=S | 30 | D | 9,265 | 1,853 | -0.0214 | 0.0033 | <0.001 | 0.0070 | 0.002 | 0.0067 | - | MATCH (p<.05, DK) |
| alt_D_q100k | 9415 | outcome=S | 30 | S | 9,265 | 1,853 | -0.6455 | 0.0157 | <0.001 | 0.0283 | <0.001 | 0.0281 | (no prior) | n/a (no P1 prior) |
| alt_D_q100k | 9415 | outcome=L | 1 | S | 9,410 | 1,882 | 0.0186 | 0.0091 | 0.042 | 0.0096 | 0.053 | 0.0094 | + | sign matches but not sig. (DK p=0.053) |
| alt_D_q100k | 9415 | outcome=L | 1 | D | 9,410 | 1,882 | -0.0013 | 0.0025 | 0.610 | 0.0022 | 0.566 | 0.0022 | (no prior) | n/a (no P1 prior) |
| alt_D_q100k | 9415 | outcome=L | 1 | L | 9,410 | 1,882 | -0.0090 | 0.0029 | 0.002 | 0.0031 | 0.004 | 0.0032 | (no prior) | n/a (no P1 prior) |
| alt_D_q100k | 9415 | outcome=L | 7 | S | 9,380 | 1,876 | 0.0362 | 0.0114 | 0.002 | 0.0145 | 0.013 | 0.0128 | + | MATCH (p<.05, DK) |
| alt_D_q100k | 9415 | outcome=L | 7 | D | 9,380 | 1,876 | -0.0086 | 0.0036 | 0.018 | 0.0049 | 0.080 | 0.0047 | (no prior) | n/a (no P1 prior) |
| alt_D_q100k | 9415 | outcome=L | 7 | L | 9,380 | 1,876 | -0.0189 | 0.0042 | <0.001 | 0.0077 | 0.014 | 0.0093 | (no prior) | n/a (no P1 prior) |
| alt_D_q100k | 9415 | outcome=L | 14 | S | 9,345 | 1,869 | 0.0461 | 0.0147 | 0.002 | 0.0244 | 0.059 | 0.0272 | + | sign matches but not sig. (DK p=0.059) |
| alt_D_q100k | 9415 | outcome=L | 14 | D | 9,345 | 1,869 | -0.0125 | 0.0046 | 0.007 | 0.0081 | 0.119 | 0.0087 | (no prior) | n/a (no P1 prior) |
| alt_D_q100k | 9415 | outcome=L | 14 | L | 9,345 | 1,869 | -0.0274 | 0.0054 | <0.001 | 0.0146 | 0.060 | 0.0152 | (no prior) | n/a (no P1 prior) |
| alt_D_q100k | 9415 | outcome=L | 30 | S | 9,265 | 1,853 | 0.0810 | 0.0154 | <0.001 | 0.0341 | 0.018 | 0.0348 | + | MATCH (p<.05, DK) |
| alt_D_q100k | 9415 | outcome=L | 30 | D | 9,265 | 1,853 | -0.0210 | 0.0055 | <0.001 | 0.0138 | 0.128 | 0.0132 | (no prior) | n/a (no P1 prior) |
| alt_D_q100k | 9415 | outcome=L | 30 | L | 9,265 | 1,853 | -0.0435 | 0.0065 | <0.001 | 0.0271 | 0.109 | 0.0260 | (no prior) | n/a (no P1 prior) |
| alt_D_q100k | 9415 | outcome=D | 1 | L | 9,410 | 1,882 | -0.0075 | 0.0064 | 0.240 | 0.0054 | 0.164 | 0.0076 | - | sign matches but not sig. (DK p=0.164) |
| alt_D_q100k | 9415 | outcome=D | 1 | S | 9,410 | 1,882 | -0.1267 | 0.0267 | <0.001 | 0.0273 | <0.001 | 0.0382 | (no prior) | n/a (no P1 prior) |
| alt_D_q100k | 9415 | outcome=D | 1 | D | 9,410 | 1,882 | -0.4803 | 0.0113 | <0.001 | 0.0163 | <0.001 | 0.0266 | (no prior) | n/a (no P1 prior) |
| alt_D_q100k | 9415 | outcome=D | 7 | L | 9,380 | 1,876 | -0.0047 | 0.0066 | 0.473 | 0.0089 | 0.596 | 0.0102 | - | sign matches but not sig. (DK p=0.596) |
| alt_D_q100k | 9415 | outcome=D | 7 | S | 9,380 | 1,876 | -0.1422 | 0.0295 | <0.001 | 0.0409 | <0.001 | 0.0513 | (no prior) | n/a (no P1 prior) |
| alt_D_q100k | 9415 | outcome=D | 7 | D | 9,380 | 1,876 | -0.5966 | 0.0119 | <0.001 | 0.0196 | <0.001 | 0.0332 | (no prior) | n/a (no P1 prior) |
| alt_D_q100k | 9415 | outcome=D | 14 | L | 9,345 | 1,869 | -0.0065 | 0.0068 | 0.340 | 0.0111 | 0.558 | 0.0127 | - | sign matches but not sig. (DK p=0.558) |
| alt_D_q100k | 9415 | outcome=D | 14 | S | 9,345 | 1,869 | -0.1025 | 0.0296 | <0.001 | 0.0484 | 0.034 | 0.0516 | (no prior) | n/a (no P1 prior) |
| alt_D_q100k | 9415 | outcome=D | 14 | D | 9,345 | 1,869 | -0.6336 | 0.0117 | <0.001 | 0.0231 | <0.001 | 0.0285 | (no prior) | n/a (no P1 prior) |
| alt_D_q100k | 9415 | outcome=D | 30 | L | 9,265 | 1,853 | 0.0035 | 0.0065 | 0.588 | 0.0140 | 0.802 | 0.0144 | - | WRONG SIGN (predicted -, got +) |
| alt_D_q100k | 9415 | outcome=D | 30 | S | 9,265 | 1,853 | -0.1269 | 0.0313 | <0.001 | 0.0722 | 0.079 | 0.0667 | (no prior) | n/a (no P1 prior) |
| alt_D_q100k | 9415 | outcome=D | 30 | D | 9,265 | 1,853 | -0.6862 | 0.0115 | <0.001 | 0.0265 | <0.001 | 0.0262 | (no prior) | n/a (no P1 prior) |

