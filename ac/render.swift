// Draws caption frames with macOS's own text engine: every installed font (the
// downloadable Chinese ones too), colour emoji, proper Thai shaping.
//
// Reads one JSON job per line on stdin, writes a transparent PNG, prints "ok" or "error: ...".
//   {"out": "/path.png", "w": 1920, "h": 1080, "blocks": [Block]}
// Block: {"x": 0..1, "y": 0..1, "anchor": "bottom"|"top"|"center", "maxw": 0..1, "gap": px,
//         "box": {"color": "#RRGGBBAA", "pad": px, "radius": px} | null,
//         "rows": [{"text", "font", "size", "color", "bold", "stroke", "stroke_color", "shadow", "shadow_color",
//                   "paint": [[start, length, "#RRGGBB"]]}]}     paint: some words in their own colour (UTF-16 ranges)
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
    // Many free fonts don't call their regular weight "5" (or are variable fonts): take the member of
    // the family whose weight is closest to what's wanted, by its PostScript name.
    if let f = family, let members = fm.availableMembers(ofFontFamily: f), !members.isEmpty {
        let want = bold ? 9 : 5
        let best = members.min { a, b in
            abs(((a[2] as? NSNumber)?.intValue ?? 5) - want) < abs(((b[2] as? NSNumber)?.intValue ?? 5) - want)
        }
        if let ps = best?[0] as? String, let nf = NSFont(name: ps, size: size) { return nf }
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
    let filled = NSMutableAttributedString(string: text, attributes: fill)
    let n = (text as NSString).length
    for p in (r["paint"] as? [[Any]]) ?? [] {
        guard p.count == 3, let a = p[0] as? Int, let len = p[1] as? Int, let hex = p[2] as? String,
              a >= 0, len > 0, a + len <= n else { continue }
        filled.addAttribute(.foregroundColor, value: color(hex, .white), range: NSRange(location: a, length: len))
    }
    var row = Row(text: filled, outline: outline, shadow: sh)
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
                let rect = CGRect(x: x, y: y, width: w, height: h)
                let hints: [NSImageRep.HintKey: Any] = [.interpolation: NSImageInterpolation.high.rawValue]
                // badge: the logo on a rounded (or round) backing
                if let plate = b["plate"] as? [String: Any] {
                    let pad = CGFloat((plate["pad"] as? Double) ?? 0.12) * w
                    var r = rect.insetBy(dx: -pad, dy: -pad)
                    if (plate["shape"] as? String) == "circle" {
                        let d = max(r.width, r.height); r = CGRect(x: r.midX - d / 2, y: r.midY - d / 2, width: d, height: d)
                    }
                    let rad = (plate["shape"] as? String) == "circle" ? r.width / 2 : min(r.width, r.height) * 0.22
                    color(plate["color"] as? String, NSColor(white: 1, alpha: 0.85)).setFill()
                    NSBezierPath(roundedRect: r, xRadius: rad, yRadius: rad).fill()
                }
                // outline: the logo's shape in a contrasting colour, spread a little in every direction
                if let halo = b["halo"] as? [String: Any] {
                    let width = max(1, CGFloat((halo["width"] as? Double) ?? 0.012) * w)
                    let tint = color(halo["color"] as? String, .black)
                    let sil = NSImage(size: img.size, flipped: false) { r in
                        img.draw(in: r); tint.set(); r.fill(using: .sourceIn); return true
                    }
                    let steps = 24
                    for i in 0..<steps {
                        let a = CGFloat(i) / CGFloat(steps) * 2 * .pi
                        for k in [0.5, 1.0] as [CGFloat] {
                            sil.draw(in: rect.offsetBy(dx: cos(a) * width * k, dy: sin(a) * width * k), from: .zero,
                                     operation: .sourceOver, fraction: 1, respectFlipped: true, hints: hints)
                        }
                    }
                }
                // soft shadow
                let blur = CGFloat((b["shadow"] as? Double) ?? 0) * w
                NSGraphicsContext.saveGraphicsState()
                if blur > 0 {
                    let sh = NSShadow(); sh.shadowBlurRadius = blur; sh.shadowOffset = NSSize(width: 0, height: -blur * 0.2)
                    sh.shadowColor = color(b["shadow_color"] as? String, NSColor(white: 0, alpha: 0.85)); sh.set()
                }
                img.draw(in: rect, from: .zero, operation: .sourceOver, fraction: 1, respectFlipped: true, hints: hints)
                if blur > 0 {   // twice, so the glow is strong enough to read on busy pictures
                    img.draw(in: rect, from: .zero, operation: .sourceOver, fraction: 1, respectFlipped: true, hints: hints)
                }
                NSGraphicsContext.restoreGraphicsState()
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
// "fontfiles <family>…": where each family's fonts are, so the page can be given them (Safari only lets
// pages use the fonts every Mac has). One JSON object per font: family, ps (PostScript name), weight
// (CSS 100-900), path.
if CommandLine.arguments.count > 1 && CommandLine.arguments[1] == "fontfiles" {
    for fam in CommandLine.arguments.dropFirst(2) {
        for m in NSFontManager.shared.availableMembers(ofFontFamily: fam) ?? [] {
            guard let ps = m.first as? String, let w = m[2] as? Int else { continue }
            let font = CTFontCreateWithName(ps as CFString, 12, nil)
            guard let url = CTFontCopyAttribute(font, kCTFontURLAttribute) as? URL else { continue }
            let css = [100, 100, 200, 300, 300, 400, 500, 600, 600, 700, 700, 800, 800, 900, 900, 900][max(0, min(15, w))]
            let row: [String: Any] = ["family": fam, "ps": ps, "weight": css, "path": url.path]
            if let d = try? JSONSerialization.data(withJSONObject: row), let j = String(data: d, encoding: .utf8) { print(j) }
        }
    }
    exit(0)
}
setvbuf(stdout, nil, _IOLBF, 0)
// fonts in ~/Library/Fonts, registered for this process so they draw even right after being installed
let userFonts = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Fonts")
for f in (try? FileManager.default.contentsOfDirectory(at: userFonts, includingPropertiesForKeys: nil)) ?? []
    where ["ttf", "otf", "ttc"].contains(f.pathExtension.lowercased()) {
    CTFontManagerRegisterFontsForURL(f as CFURL, .process, nil)
}
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
