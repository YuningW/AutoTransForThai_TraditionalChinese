// Draws caption frames with macOS's own text engine: every installed font (the
// downloadable Chinese ones too), colour emoji, proper Thai shaping.
//
// Reads one JSON job per line on stdin, writes a transparent PNG, prints "ok" or "error: ...".
//   {"out": "/path.png", "w": 1920, "h": 1080, "blocks": [Block]}
// Block: {"x": 0..1, "y": 0..1, "anchor": "bottom"|"top"|"center", "maxw": 0..1, "gap": px,
//         "box": {"color": "#RRGGBBAA", "pad": px, "radius": px} | null,
//         "rows": [{"text", "font", "size", "color", "bold", "stroke", "stroke_color", "shadow", "shadow_color"}]}
// With argument "fonts" it prints the installed font families, one per line.
import AppKit
import Foundation

func color(_ hex: String?, _ fallback: NSColor) -> NSColor {
    guard var s = hex, s.hasPrefix("#") else { return fallback }
    s.removeFirst()
    if s.count == 6 { s += "FF" }
    guard s.count == 8, let v = UInt64(s, radix: 16) else { return fallback }
    return NSColor(srgbRed: CGFloat((v >> 24) & 255) / 255, green: CGFloat((v >> 16) & 255) / 255,
                   blue: CGFloat((v >> 8) & 255) / 255, alpha: CGFloat(v & 255) / 255)
}

func font(_ family: String?, _ size: CGFloat, _ bold: Bool) -> NSFont {
    let fm = NSFontManager.shared
    if let f = family, let nf = fm.font(withFamily: f, traits: bold ? .boldFontMask : [], weight: bold ? 9 : 5, size: size) {
        return nf
    }
    if let f = family, let nf = NSFont(name: f, size: size) { return nf }
    return bold ? NSFont.boldSystemFont(ofSize: size) : NSFont.systemFont(ofSize: size)
}

struct Row {
    let text: NSAttributedString      // fill
    let outline: NSAttributedString?  // stroke pass, drawn first
    let shadow: NSShadow?
    var size: CGSize = .zero
}

func makeRow(_ r: [String: Any], maxWidth: CGFloat) -> Row {
    let text = (r["text"] as? String) ?? ""
    let size = CGFloat((r["size"] as? Double) ?? 48)
    let f = font(r["font"] as? String, size, (r["bold"] as? Bool) ?? false)
    let para = NSMutableParagraphStyle()
    para.alignment = .center
    para.lineBreakMode = .byWordWrapping
    para.lineHeightMultiple = 1.08
    let fill: [NSAttributedString.Key: Any] = [.font: f, .foregroundColor: color(r["color"] as? String, .white), .paragraphStyle: para]
    var outline: NSAttributedString? = nil
    let stroke = CGFloat((r["stroke"] as? Double) ?? 0)
    if stroke > 0 {
        // the stroke is centred on the glyph edge, so twice the width shows `stroke` px outside
        outline = NSAttributedString(string: text, attributes: [
            .font: f, .paragraphStyle: para, .foregroundColor: NSColor.clear,
            .strokeColor: color(r["stroke_color"] as? String, .black), .strokeWidth: 2 * stroke / size * 100])
    }
    var sh: NSShadow? = nil
    let blur = CGFloat((r["shadow"] as? Double) ?? 0)
    if blur > 0 {
        sh = NSShadow()
        sh!.shadowBlurRadius = blur
        sh!.shadowOffset = NSSize(width: 0, height: -blur * 0.35)
        sh!.shadowColor = color(r["shadow_color"] as? String, NSColor(white: 0, alpha: 0.75))
    }
    var row = Row(text: NSAttributedString(string: text, attributes: fill), outline: outline, shadow: sh)
    let b = row.text.boundingRect(with: CGSize(width: maxWidth, height: 10000), options: [.usesLineFragmentOrigin, .usesFontLeading])
    row.size = CGSize(width: ceil(b.width) + 2 * stroke + 2, height: ceil(b.height) + 2 * stroke)
    return row
}

func draw(_ job: [String: Any]) throws {
    let W = (job["w"] as? Int) ?? 1920, H = (job["h"] as? Int) ?? 1080
    guard let out = job["out"] as? String else { throw NSError(domain: "render", code: 1, userInfo: [NSLocalizedDescriptionKey: "no out"]) }
    let cs = CGColorSpace(name: CGColorSpace.sRGB)!
    guard let ctx = CGContext(data: nil, width: W, height: H, bitsPerComponent: 8, bytesPerRow: 0, space: cs,
                              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return }
    ctx.translateBy(x: 0, y: CGFloat(H))
    ctx.scaleBy(x: 1, y: -1)
    ctx.setLineJoin(.round)
    ctx.setLineCap(.round)
    let ns = NSGraphicsContext(cgContext: ctx, flipped: true)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = ns
    for b in (job["blocks"] as? [[String: Any]]) ?? [] {
        // see-through: the whole block (text, outline, box, picture) at this opacity
        let opacity = CGFloat((b["opacity"] as? Double) ?? 1)
        if opacity < 0.999 {
            ctx.saveGState()
            ctx.setAlpha(max(0.02, opacity))
            ctx.beginTransparencyLayer(auxiliaryInfo: nil)
        }
        defer { if opacity < 0.999 { ctx.endTransparencyLayer(); ctx.restoreGState() } }
        // a picture (your logo): width as a share of the frame, centred on x/y
        if let path = b["image"] as? String {
            if let img = NSImage(contentsOfFile: path), img.size.width > 0 {
                let w = CGFloat((b["w"] as? Double) ?? 0.15) * CGFloat(W)
                let h = w * img.size.height / img.size.width
                var x = CGFloat((b["x"] as? Double) ?? 0.5) * CGFloat(W) - w / 2
                var y = CGFloat((b["y"] as? Double) ?? 0.5) * CGFloat(H) - h / 2
                x = max(0, min(x, CGFloat(W) - w)); y = max(0, min(y, CGFloat(H) - h))
                img.draw(in: CGRect(x: x, y: y, width: w, height: h), from: .zero, operation: .sourceOver, fraction: 1,
                         respectFlipped: true, hints: [.interpolation: NSImageInterpolation.high.rawValue])
            }
            continue
        }
        let maxW = CGFloat((b["maxw"] as? Double) ?? 0.88) * CGFloat(W)
        let rows = ((b["rows"] as? [[String: Any]]) ?? []).filter { !(($0["text"] as? String) ?? "").isEmpty }.map { makeRow($0, maxWidth: maxW) }
        if rows.isEmpty { continue }
        let gap = CGFloat((b["gap"] as? Double) ?? 4)
        let totalH = rows.map { $0.size.height }.reduce(0, +) + gap * CGFloat(rows.count - 1)
        let blockW = rows.map { $0.size.width }.max() ?? 0
        let cx = CGFloat((b["x"] as? Double) ?? 0.5) * CGFloat(W)
        let ay = CGFloat((b["y"] as? Double) ?? 0.94) * CGFloat(H)
        var top: CGFloat
        switch (b["anchor"] as? String) ?? "bottom" {
        case "top": top = ay
        case "center": top = ay - totalH / 2
        default: top = ay - totalH
        }
        top = max(2, min(top, CGFloat(H) - totalH - 2))
        let left = max(2, min(cx - blockW / 2, CGFloat(W) - blockW - 2))
        if let box = b["box"] as? [String: Any] {
            let pad = CGFloat((box["pad"] as? Double) ?? 12)
            let r = CGRect(x: left - pad, y: top - pad * 0.6, width: blockW + 2 * pad, height: totalH + 1.2 * pad)
            let rad = CGFloat((box["radius"] as? Double) ?? 10)
            color(box["color"] as? String, NSColor(white: 0, alpha: 0.55)).setFill()
            NSBezierPath(roundedRect: r, xRadius: rad, yRadius: rad).fill()
        }
        var y = top
        for row in rows {
            let rect = CGRect(x: left + (blockW - row.size.width) / 2, y: y, width: row.size.width, height: row.size.height + 4)
            NSGraphicsContext.saveGraphicsState()
            if let sh = row.shadow { sh.set() }
            if let o = row.outline { o.draw(with: rect, options: [.usesLineFragmentOrigin, .usesFontLeading]) }
            else if row.shadow != nil { row.text.draw(with: rect, options: [.usesLineFragmentOrigin, .usesFontLeading]) }
            NSGraphicsContext.restoreGraphicsState()
            row.text.draw(with: rect, options: [.usesLineFragmentOrigin, .usesFontLeading])
            y += row.size.height + gap
        }
    }
    NSGraphicsContext.restoreGraphicsState()
    guard let img = ctx.makeImage(),
          let dest = CGImageDestinationCreateWithURL(URL(fileURLWithPath: out) as CFURL, "public.png" as CFString, 1, nil)
    else { throw NSError(domain: "render", code: 2, userInfo: [NSLocalizedDescriptionKey: "can't write \(out)"]) }
    CGImageDestinationAddImage(dest, img, nil)
    if !CGImageDestinationFinalize(dest) { throw NSError(domain: "render", code: 3, userInfo: [NSLocalizedDescriptionKey: "can't write \(out)"]) }
}

if CommandLine.arguments.count > 1 && CommandLine.arguments[1] == "fonts" {
    for f in NSFontManager.shared.availableFontFamilies { print(f) }
    exit(0)
}
setvbuf(stdout, nil, _IOLBF, 0)
while let line = readLine() {
    autoreleasepool {
        do {
            guard let data = line.data(using: .utf8),
                  let job = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { print("error: bad json"); return }
            try draw(job)
            print("ok")
        } catch {
            print("error: \(error.localizedDescription)")
        }
    }
}
