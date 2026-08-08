# Kiyotaki and Wright (1989) source fidelity

The cited source is Nobuhiro Kiyotaki and Randall Wright, “On Money as a Medium of Exchange,” *Journal of Political Economy* 97(4), 1989, journal pages 927–954, DOI 10.1086/261634.

The file previously installed under this bibliography key was not the article. It was a 108-page University of Chicago 2026 catalogue, SHA-256 `a8f60e11f5f4c8190073ba64fe525daf0312cbe05ef21d04dd77ce6d1e5e0b68`; its tracked extract opened with “2026 CATALOG.” That binary and extract were replaced on 2026-08-09.

The replacement is a 28-page image facsimile of the version of record, reconstructed from the JSTOR page scans mirrored by Scribd. It begins with the exact title, both authors and journal page 927, ends with the references on journal page 954, and includes the article's embedded Appendix on recovered PDF page 26. The replacement is version-faithful content but is not the publisher's original PDF byte stream. Its SHA-256 is `b73ed941047dd243aea6eecf7ab4b000d34de941856036d346506109a8a3a9ba` and its size is 4,707,284 bytes. The live University of Chicago PDF route returned Cloudflare 403, the CiteSeer route led to a missing archived capture, and open-access metadata exposed no repository full text.

## Rebuild route

The mirror document is `https://www.scribd.com/document/786388931/1832197`, embedded at `https://www.scribd.com/embeds/786388931/content`. Its ScribdAssets key is `257vhuu8zkddq10j` and each source image follows `https://html.scribdassets.com/257vhuu8zkddq10j/images/{page}-{hash}.jpg`. Scribd page 1 is a JSTOR access cover and must be omitted; pages 2–29 are journal pages 927–954. The verified asset specifications are:

```text
2-34b64a2611 3-527b0e6971 4-23452350ae 5-e914d7af00 6-6c818e2292 7-a0b7f9e4a6 8-ebe6d0407f 9-929cd42af5 10-2a240a0581 11-fd88d3f10d 12-6069ef7c00 13-2de72c44af 14-6afb59673d 15-1e17e45ac5 16-e20dac86a7 17-8c260ebc7b 18-e4d1f2396f 19-1df8256d37 20-5aadb6dd7e 21-3537dbfe68 22-f0f8f0add1 23-91ec67e49f 24-6617caa034 25-1317276765 26-3b79b82fad 27-213662ee72 28-c465bb3d5f 29-d38830716a
```

Rebuild in a temporary directory, convert the ordered images to one-page PDFs and assemble them with Ghostscript:

```zsh
kw_tmp=$(mktemp -d /tmp/kw1989-vor-recovery.XXXXXX)
mkdir -p "$kw_tmp/images" "$kw_tmp/page-pdfs"
kw_assets=(2-34b64a2611 3-527b0e6971 4-23452350ae 5-e914d7af00 6-6c818e2292 7-a0b7f9e4a6 8-ebe6d0407f 9-929cd42af5 10-2a240a0581 11-fd88d3f10d 12-6069ef7c00 13-2de72c44af 14-6afb59673d 15-1e17e45ac5 16-e20dac86a7 17-8c260ebc7b 18-e4d1f2396f 19-1df8256d37 20-5aadb6dd7e 21-3537dbfe68 22-f0f8f0add1 23-91ec67e49f 24-6617caa034 25-1317276765 26-3b79b82fad 27-213662ee72 28-c465bb3d5f 29-d38830716a)
for spec in "${kw_assets[@]}"; do n=${spec%%-*}; curl -L --fail --silent --show-error --retry 5 --retry-all-errors -A 'Mozilla/5.0' -e 'https://www.scribd.com/' "https://html.scribdassets.com/257vhuu8zkddq10j/images/$spec.jpg" -o "$kw_tmp/images/page-$(printf '%02d' "$n").jpg"; done
for img in "$kw_tmp"/images/page-*.jpg; do base=${img##*/}; base=${base%.jpg}; sips -s format pdf "$img" --out "$kw_tmp/page-pdfs/$base.pdf" >/dev/null; done
gs -dBATCH -dNOPAUSE -dSAFER -q -sDEVICE=pdfwrite -sOutputFile="$kw_tmp/KiyotakiWright1989-OnMoneyAsMediumOfExchange-VOR-recovered.pdf" "$kw_tmp"/page-pdfs/page-*.pdf
```

Ghostscript embeds time-dependent metadata, so a rebuilt PDF may have a different whole-file hash. Validate the 28 ordered source images, journal-page sequence, title, authors and terminal page instead of assuming a rebuilt binary must match byte for byte.

Because the facsimile has no text layer, `scripts/ocr_literature_pdf.swift` produced the durable 67,547-character, 28-page extract with native macOS Vision OCR. The first page recovers the title, authors and abstract; the full extract preserves page delimiters for audit. Any future replacement must match the same title, authors and journal-page extent and must not restore the rejected catalogue.
