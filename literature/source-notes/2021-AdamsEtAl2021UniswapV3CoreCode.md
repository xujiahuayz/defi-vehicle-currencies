# Uniswap v3 core v1.0.0 source package

- Artifact: `literature/papers/2021-AdamsEtAl2021UniswapV3CoreCode-source-v1.0.0.tar.gz`
- Official repository tag: `v1.0.0`
- Annotated tag object: `ef64f51d0f0dca5346c903484f3e6a771dd69d59`
- Peeled commit: `e3589b192d0be27e100cd0daaf6c97204fdb1899`
- Commit date: 2021-05-04
- Bytes: 1,878,559
- - Inspected: factory and event interfaces, `UniswapV3Pool`, `Oracle`, `SwapMath`, `SqrtPriceMath`, `Tick`, `TickBitmap`, `TickMath`, `TransferHelper`, relevant gas tests, repository history, and source-package inventory.
- Boundary: this is the immutable final core implementation and the primary source for Q64.96 integer arithmetic, direction-specific rounding, tick crossing, emitted post-swap state, and oracle storage. The bundled ABDK and Trail of Bits reports reviewed beta.3 and beta.7 respectively; neither certifies this exact final tag.
- Material correction: the deployed source and current official documentation allow 65,535 oracle observations, while the whitepaper states 65,536.
