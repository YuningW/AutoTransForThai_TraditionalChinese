// Reads subtitles that are burned into a video's picture, with macOS's own text recognition
// (Vision: Thai, English, Traditional and Simplified Chinese). Runs on the Mac, nothing is sent anywhere.
//
//   ocr <video> <every-seconds> <from-y> <to-y>
// Looks at the band of the picture between from-y and to-y (0 = top, 1 = bottom) every few seconds and
// prints one JSON object per frame: {"t": seconds, "lines": [{"text", "conf", "x", "y", "h"}]} where
// x/y are the centre of each text line as fractions of the picture, then {"done": frames}.
import AVFoundation
import Foundation
import Vision

setvbuf(stdout, nil, _IOLBF, 0)
let args = CommandLine.arguments
guard args.count >= 5, let every = Double(args[2]), let fromY = Double(args[3]), let toY = Double(args[4]) else {
    print("{\"error\": \"usage: ocr <video> <every> <from-y> <to-y>\"}"); exit(1)
}
let asset = AVURLAsset(url: URL(fileURLWithPath: args[1]))
let gen = AVAssetImageGenerator(asset: asset)
gen.appliesPreferredTrackTransform = true
gen.requestedTimeToleranceBefore = CMTime(seconds: 0.1, preferredTimescale: 600)
gen.requestedTimeToleranceAfter = CMTime(seconds: 0.1, preferredTimescale: 600)
gen.maximumSize = CGSize(width: 1600, height: 1600)
let duration = CMTimeGetSeconds(asset.duration)
if !(duration > 0) { print("{\"error\": \"can't read this video\"}"); exit(1) }

func esc(_ s: String) -> String {
    let d = try! JSONSerialization.data(withJSONObject: [s])
    let j = String(data: d, encoding: .utf8)!
    return String(j.dropFirst().dropLast())
}

var t = 0.0, frames = 0
while t < duration {
    autoreleasepool {
        guard let img = try? gen.copyCGImage(at: CMTime(seconds: t, preferredTimescale: 600), actualTime: nil) else { return }
        let W = CGFloat(img.width), H = CGFloat(img.height)
        let band = CGRect(x: 0, y: H * CGFloat(fromY), width: W, height: H * CGFloat(toY - fromY)).integral
        guard let crop = img.cropping(to: band) else { return }
        let req = VNRecognizeTextRequest()
        req.recognitionLevel = .accurate
        req.recognitionLanguages = ["th-TH", "en-US", "zh-Hant", "zh-Hans"]
        req.usesLanguageCorrection = true
        try? VNImageRequestHandler(cgImage: crop, options: [:]).perform([req])
        var out: [String] = []
        for o in req.results ?? [] {
            guard let c = o.topCandidates(1).first else { continue }
            let b = o.boundingBox                       // in the band, origin bottom-left
            let cx = b.midX
            let cy = (band.minY + (1 - b.midY) * band.height) / H
            out.append("{\"text\": \(esc(c.string)), \"conf\": \(String(format: "%.2f", c.confidence)), " +
                       "\"x\": \(String(format: "%.3f", cx)), \"y\": \(String(format: "%.3f", cy)), " +
                       "\"h\": \(String(format: "%.3f", b.height * band.height / H))}")
        }
        print("{\"t\": \(String(format: "%.2f", t)), \"lines\": [\(out.joined(separator: ", "))]}")
        frames += 1
    }
    t += every
}
print("{\"done\": \(frames)}")
