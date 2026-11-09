import SwiftUI

private struct NativeMotionLibrary: Decodable {
    struct Rule: Decodable { let kind: String; let groups: [[[String]]] }
    struct Motion: Decodable {
        let direction: String
        let stageStart: String
        let stageEnd: String
        let caption: String
        let poses: [String: [[String: [Double]]]]
    }
    let rules: [Rule]
    let motions: [String: Motion]
    static let shared: NativeMotionLibrary? = {
        guard let url = Bundle.main.url(forResource:"FlutterMotionData", withExtension:"json"),
              let data = try? Data(contentsOf:url) else { return nil }
        return try? JSONDecoder().decode(NativeMotionLibrary.self, from:data)
    }()
    func kind(name: String, pattern: String) -> String {
        let value = (name + " " + pattern).lowercased()
        return rules.first { rule in rule.groups.contains { group in group.allSatisfy { terms in terms.contains { value.contains($0) } } } }?.kind ?? "generic"
    }
}

struct NativeAnatomyMotion: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePhase) private var scenePhase
    let exercise: NativeJSON
    @State private var paused = false
    @State private var anchor = Date()
    @State private var heldCycle = 0.0

    var body: some View {
        NativeCard {
            HStack {
                Label("动态解剖示意", systemImage:"figure.strengthtraining.traditional").font(.headline)
                Spacer()
                Button(paused ? "播放" : "暂停", systemImage:paused ? "play.fill" : "pause.fill") {
                    if paused { anchor = Date().addingTimeInterval(-heldCycle * 2.1) }
                    else { heldCycle = cycle(.now) }
                    paused.toggle()
                }.labelStyle(.iconOnly).frame(width:44,height:44).disabled(reduceMotion)
            }
            if let library = NativeMotionLibrary.shared {
                let kind = library.kind(name:exercise["name_zh"].text, pattern:exercise["movement_pattern"].text)
                if let motion = library.motions[kind] {
                    TimelineView(.animation(minimumInterval:1.0/30, paused:paused || reduceMotion || scenePhase != .active)) { timeline in
                        let phase = reduceMotion ? 0.58 : (paused ? heldCycle : cycle(timeline.date))
                        let progress = motionProgress(phase)
                        Canvas { context, size in
                            draw(context:context, size:size, motion:motion, kind:kind, progress:progress)
                        }.frame(height:290)
                            .background(NativeTheme.softAccent.opacity(0.4), in:RoundedRectangle(cornerRadius:16))
                            .accessibilityLabel(exercise["name_zh"].text + "动态动作示意。红色为主练肌群，黄色为辅助肌群，绿色箭头表示动作方向。")
                        Text(progress < 0.48 ? motion.stageStart : motion.stageEnd).font(.caption.weight(.semibold)).foregroundStyle(AppTab.plan.tint)
                    }
                    Text(motion.direction).font(.caption).foregroundStyle(.green)
                    if kind == "generic" { Text("这个动作使用通用姿态示意，请结合动作步骤查看。").font(.caption).foregroundStyle(NativeTheme.muted) }
                }
            } else {
                Text("动作示意资源未能读取，请更新 App。").foregroundStyle(.red)
            }
            Text("主练：" + exercise["primary_muscles"].strings.map(NativeLabels.muscle).joined(separator:"、")).font(.caption).foregroundStyle(.red)
            if !exercise["secondary_muscles"].values.isEmpty {
                Text("辅助：" + exercise["secondary_muscles"].strings.map(NativeLabels.muscle).joined(separator:"、")).font(.caption).foregroundStyle(.orange)
            }
            if reduceMotion { Text("已按系统设置减少动态效果").font(.caption).foregroundStyle(NativeTheme.muted) }
        }
    }

    private func cycle(_ date: Date) -> Double { max(0,date.timeIntervalSince(anchor)/2.1).truncatingRemainder(dividingBy:1) }
    private func motionProgress(_ phase: Double) -> Double {
        if phase <= 0.12 { return 0 }
        if phase >= 0.78 { return 1 }
        let t = (phase-0.12)/0.66
        return t*t*(3-2*t)
    }

    private func draw(context original: GraphicsContext, size: CGSize, motion: NativeMotionLibrary.Motion, kind: String, progress: Double) {
        let machine = ["machine","smith_machine"].contains(exercise["equipment"].text)
        guard let frames = motion.poses[machine ? "machine" : "bodyweight"], frames.count == 31 else { return }
        let index = min(29,Int(progress*30))
        let blend = progress*30-Double(index)
        func point(_ name: String, at fraction: Double? = nil) -> CGPoint {
            if let fraction {
                let frame = frames[min(30,max(0,Int(fraction*30)))]
                let pair = frame[name] ?? [0,0]
                return CGPoint(x:pair[0],y:pair[1])
            }
            let a = frames[index][name] ?? [0,0], b = frames[index+1][name] ?? a
            return CGPoint(x:a[0]+(b[0]-a[0])*blend,y:a[1]+(b[1]-a[1])*blend)
        }
        var context = original
        let scale = min(size.width/150,(size.height-16)/150)
        context.translateBy(x:(size.width-150*scale)/2,y:(size.height-150*scale)/2)
        context.scaleBy(x:scale,y:scale)
        func line(_ a: CGPoint, _ b: CGPoint, _ color: Color, width: CGFloat = 1.5) {
            var p = Path(); p.move(to:a); p.addLine(to:b)
            context.stroke(p,with:.color(color),style:StrokeStyle(lineWidth:width,lineCap:.round))
        }
        func ellipse(_ center: CGPoint, w: CGFloat, h: CGFloat, color: Color) {
            context.fill(Path(ellipseIn:CGRect(x:center.x-w/2,y:center.y-h/2,width:w,height:h)),with:.color(color))
        }
        let hip = CGPoint(x:(point("leftHip").x+point("rightHip").x)/2,y:(point("leftHip").y+point("rightHip").y)/2)
        let chest = CGPoint(x:(point("leftShoulder").x+point("rightShoulder").x)/2,y:(point("leftShoulder").y+hip.y)/2)
        if kind == "benchPress" || (kind == "chestFly" && exercise["equipment"].text == "dumbbell") {
            context.fill(Path(roundedRect:CGRect(x:52,y:2,width:46,height:142),cornerRadius:13),with:.color(NativeTheme.accent.opacity(0.12)))
        } else {
            for y in [35.0,70.0,105.0] { line(CGPoint(x:16,y:y),CGPoint(x:134,y:y),NativeTheme.muted.opacity(0.14),width:0.6) }
            line(CGPoint(x:14,y:143),CGPoint(x:136,y:143),NativeTheme.muted.opacity(0.3),width:0.7)
        }
        if machine {
            line(CGPoint(x:26,y:24),CGPoint(x:26,y:137),.gray.opacity(0.4),width:2)
            line(CGPoint(x:26,y:137),CGPoint(x:127,y:137),.gray.opacity(0.4),width:2)
            line(CGPoint(x:hip.x-16,y:hip.y+5),CGPoint(x:hip.x+22,y:hip.y+5),NativeTheme.accent.opacity(0.4),width:5)
        }
        let segments = [("leftShoulder","leftElbow"),("leftElbow","leftHand"),("rightShoulder","rightElbow"),("rightElbow","rightHand"),("leftHip","leftKnee"),("leftKnee","leftAnkle"),("rightHip","rightKnee"),("rightKnee","rightAnkle")]
        for (a,b) in segments { line(point(a,at:0),point(b,at:0),NativeTheme.muted.opacity(0.13),width:9) }
        var torso = Path()
        torso.move(to:point("leftShoulder")); torso.addQuadCurve(to:point("rightShoulder"),control:point("neck"))
        torso.addLine(to:point("rightHip")); torso.addQuadCurve(to:point("leftHip"),control:CGPoint(x:hip.x,y:hip.y+5)); torso.closeSubpath()
        context.fill(torso,with:.color(NativeTheme.color(0xD5DEEA)))
        context.stroke(torso,with:.color(NativeTheme.ink.opacity(0.65)),lineWidth:1.2)
        for (a,b) in segments { line(point(a),point(b),NativeTheme.ink.opacity(0.6),width:10); line(point(a),point(b),NativeTheme.color(0xE2E8F0),width:7.5) }
        line(point("head"),point("neck"),NativeTheme.color(0xD5DEEA),width:7)
        ellipse(point("head"),w:19,h:19,color:NativeTheme.ink.opacity(0.6)); ellipse(point("head"),w:17,h:17,color:NativeTheme.color(0xE2E8F0))
        func highlight(_ muscles: [String], color: Color, width: CGFloat) {
            let keys = Set(muscles)
            if !keys.isDisjoint(with:["chest","pectorals"]) { ellipse(CGPoint(x:chest.x-6,y:chest.y-3),w:11,h:9,color:color); ellipse(CGPoint(x:chest.x+6,y:chest.y-3),w:11,h:9,color:color) }
            if keys.contains("shoulders") { ellipse(point("leftShoulder"),w:9,h:8,color:color); ellipse(point("rightShoulder"),w:9,h:8,color:color) }
            for side in ["left","right"] {
                if !keys.isDisjoint(with:["biceps","triceps"]) { line(point(side+"Shoulder"),point(side+"Elbow"),color,width:width) }
                if keys.contains("forearms") { line(point(side+"Elbow"),point(side+"Hand"),color,width:width-2) }
                if !keys.isDisjoint(with:["quadriceps","quads","hamstrings","adductors"]) { line(point(side+"Hip"),point(side+"Knee"),color,width:width) }
                if keys.contains("calves") { line(point(side+"Knee"),point(side+"Ankle"),color,width:width-2) }
            }
            if !keys.isDisjoint(with:["gluteus","glutes"]) { ellipse(hip,w:18,h:10,color:color) }
            if !keys.isDisjoint(with:["core","abs","hip_flexors"]) { ellipse(CGPoint(x:chest.x,y:(chest.y+hip.y)/2),w:15,h:16,color:color) }
            if !keys.isDisjoint(with:["back","upper_back","lats","trapezius","lower_back"]) { line(chest,hip,color,width:width+2) }
        }
        highlight(exercise["secondary_muscles"].strings,color:.orange.opacity(0.75),width:6)
        highlight(exercise["primary_muscles"].strings,color:.red.opacity(0.8),width:8)
        for joint in ["leftShoulder","rightShoulder","leftElbow","rightElbow","leftKnee","rightKnee"] { ellipse(point(joint),w:4,h:4,color:.white.opacity(0.9)) }
        let tool = exercise["equipment"].text
        if ["barbell","smith_machine"].contains(tool) {
            line(point("leftHand"),point("rightHand"),.gray,width:2.5)
            for hand in ["leftHand","rightHand"] { ellipse(point(hand),w:7,h:13,color:NativeTheme.ink) }
        } else if ["dumbbell","kettlebell"].contains(tool) {
            for hand in ["leftHand","rightHand"] { ellipse(point(hand),w:12,h:6,color:NativeTheme.ink) }
        } else if ["cable","band"].contains(tool) {
            for hand in ["leftHand","rightHand"] { line(point(hand),CGPoint(x:kind == "lowToHighFly" ? 12 : 130,y:kind == "lowToHighFly" ? 140 : 8),.gray.opacity(0.5),width:0.9) }
        }
        let lower = ["legPress","kneeExtension","lyingLegCurl","seatedLegCurl","seatedHipAbduction","seatedHipAdduction","calfRaise","seatedCalfRaise"].contains(kind)
        let arrowJoint = lower ? "rightAnkle" : (["hipThrust","gluteBridge"].contains(kind) ? "rightHip" : "rightHand")
        let start = point(arrowJoint,at:0), end = point(arrowJoint,at:1)
        let dx = end.x-start.x, dy = end.y-start.y, length = hypot(dx,dy)
        if length > 3 {
            let a = CGPoint(x:start.x+10,y:start.y), b = CGPoint(x:end.x+10,y:end.y)
            line(a,b,.green.opacity(0.85),width:1.5)
            let vx = dx/length, vy = dy/length
            line(b,CGPoint(x:b.x-vx*6+vy*3,y:b.y-vy*6-vx*3),.green,width:1.5)
            line(b,CGPoint(x:b.x-vx*6-vy*3,y:b.y-vy*6+vx*3),.green,width:1.5)
        }
    }
}
