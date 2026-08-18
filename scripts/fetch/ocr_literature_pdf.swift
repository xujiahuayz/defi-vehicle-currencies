#!/usr/bin/env swift

import AppKit
import Foundation
import PDFKit
import Vision

enum OCRError: Error, CustomStringConvertible {
    case usage
    case unreadablePDF(String)
    case renderFailure(Int)

    var description: String {
        switch self {
        case .usage:
            return "usage: ocr_literature_pdf.swift INPUT.pdf OUTPUT.txt"
        case .unreadablePDF(let path):
            return "could not open PDF: \(path)"
        case .renderFailure(let page):
            return "could not render PDF page \(page)"
        }
    }
}

func pageText(_ page: PDFPage, pageNumber: Int) throws -> String {
    let bounds = page.bounds(for: .mediaBox)
    let longestSide = max(bounds.width, bounds.height)
    let scale = max(2.0, min(4.0, 3200.0 / longestSide))
    let image = page.thumbnail(
        of: NSSize(width: bounds.width * scale, height: bounds.height * scale),
        for: .mediaBox
    )
    var imageBounds = NSRect(origin: .zero, size: image.size)
    guard let cgImage = image.cgImage(forProposedRect: &imageBounds, context: nil, hints: nil) else {
        throw OCRError.renderFailure(pageNumber)
    }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    request.recognitionLanguages = ["en-US"]
    try VNImageRequestHandler(cgImage: cgImage, options: [:]).perform([request])
    let observations = (request.results ?? []).sorted {
        let verticalGap = $0.boundingBox.maxY - $1.boundingBox.maxY
        return abs(verticalGap) > 0.01 ? verticalGap > 0 : $0.boundingBox.minX < $1.boundingBox.minX
    }
    return observations.compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
}

func main() throws {
    guard CommandLine.arguments.count == 3 else { throw OCRError.usage }
    let input = CommandLine.arguments[1]
    let output = CommandLine.arguments[2]
    guard let document = PDFDocument(url: URL(fileURLWithPath: input)) else {
        throw OCRError.unreadablePDF(input)
    }
    var pages: [String] = []
    pages.reserveCapacity(document.pageCount)
    for index in 0..<document.pageCount {
        guard let page = document.page(at: index) else { throw OCRError.renderFailure(index + 1) }
        let text = try autoreleasepool { try pageText(page, pageNumber: index + 1) }
        pages.append("\n\n===== PAGE \(index + 1) =====\n\n\(text)")
        FileHandle.standardError.write(Data("OCR \(index + 1)/\(document.pageCount)\n".utf8))
    }
    try pages.joined().write(
        to: URL(fileURLWithPath: output),
        atomically: true,
        encoding: .utf8
    )
}

do {
    try main()
} catch {
    FileHandle.standardError.write(Data("\(error)\n".utf8))
    exit(1)
}
