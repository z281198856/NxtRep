import SwiftUI
import PhotosUI
import ImageIO
import UniformTypeIdentifiers
import AVFoundation

private final class NativeNoRedirect: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
}

enum NativeMediaTransfer {
    static func perform(_ request: URLRequest, upload: Data? = nil) async throws -> Data {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 60
        config.timeoutIntervalForResource = 180
        let session = URLSession(configuration:config,delegate:NativeNoRedirect(),delegateQueue:nil)
        defer { session.invalidateAndCancel() }
        let data: Data
        let response: URLResponse
        if let upload { (data,response) = try await session.upload(for:request,from:upload) }
        else { (data,response) = try await session.data(for:request) }
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { throw NativeAPIError.message("图片传输未完成，请重新加载或上传。") }
        return data
    }

    static func jpeg(_ data: Data, capabilities: NativeJSON) throws -> Data {
        guard capabilities["accepted_content_types"].strings.contains("image/jpeg"),
              let source = CGImageSourceCreateWithData(data as CFData,nil),
              let info = CGImageSourceCopyPropertiesAtIndex(source,0,nil) as? [CFString:Any],
              let w = info[kCGImagePropertyPixelWidth] as? NSNumber,
              let h = info[kCGImagePropertyPixelHeight] as? NSNumber else { throw NativeAPIError.message("无法读取这张图片，请重新选择。") }
        let width = w.doubleValue, height = h.doubleValue
        let maxDimension = capabilities["max_dimension"].double, maxPixels = capabilities["max_pixels"].double
        guard width > 0, height > 0, maxDimension > 0, maxPixels > 0 else { throw NativeAPIError.message("图片上传限制无法读取，请重试。") }
        let scale = min(1,min(maxDimension/max(width,height),sqrt(maxPixels/(width*height))))
        let qualities = [0.88,0.78,0.68,0.58,0.48,0.38,0.30]
        for (index,quality) in qualities.enumerated() {
            let shrink = index >= 3 ? pow(0.85,Double(index-2)) : 1
            let side = max(1,Int(max(width,height)*scale*shrink))
            let options: [CFString:Any] = [kCGImageSourceCreateThumbnailFromImageAlways:true,kCGImageSourceCreateThumbnailWithTransform:true,kCGImageSourceThumbnailMaxPixelSize:side,kCGImageSourceShouldCacheImmediately:true]
            guard let image = CGImageSourceCreateThumbnailAtIndex(source,0,options as CFDictionary) else { continue }
            let output = NSMutableData()
            guard let destination = CGImageDestinationCreateWithData(output as CFMutableData,UTType.jpeg.identifier as CFString,1,nil) else { continue }
            CGImageDestinationAddImage(destination,image,[kCGImageDestinationLossyCompressionQuality:quality] as CFDictionary)
            guard CGImageDestinationFinalize(destination) else { continue }
            if output.length <= capabilities["max_bytes"].integer && image.width*image.height <= Int(maxPixels) && max(image.width,image.height) <= Int(maxDimension) { return output as Data }
        }
        throw NativeAPIError.message("图片压缩后仍超出限制，请换一张图片。")
    }
}

struct NativeImageSelector: View {
    @EnvironmentObject private var session: NativeSession
    let purpose: String
    let onUploaded: (String) -> Void
    @State private var selection: PhotosPickerItem?
    @State private var preview: Data?
    @State private var uploading = false
    @State private var error: String?
    @State private var camera = false
    @State private var uploaded = false
    var body: some View {
        VStack(alignment:.leading,spacing:12) {
            HStack {
                PhotosPicker(selection:$selection,matching:.images) { Label("从相册选择",systemImage:"photo") }.buttonStyle(.bordered)
                if UIImagePickerController.isSourceTypeAvailable(.camera) {
                    Button { Task {
                        let granted: Bool
                        if AVCaptureDevice.authorizationStatus(for:.video) == .authorized { granted = true }
                        else { granted = await AVCaptureDevice.requestAccess(for:.video) }
                        if granted { camera = true } else { error = "请在系统设置中允许 NxtRep 使用相机。" }
                    } } label:{Label("拍照",systemImage:"camera")}.buttonStyle(.bordered)
                }
            }.disabled(uploading)
            if uploading { ProgressView("正在处理并上传图片…") }
            NativeErrorText(message:error)
            if let preview, let image = UIImage(data:preview) { Image(uiImage:image).resizable().scaledToFit().frame(maxHeight:240).clipShape(RoundedRectangle(cornerRadius:14)) }
            if let preview,!uploading,!uploaded { Button("重试上传保留的照片") { Task { await upload(preview) } }.buttonStyle(.bordered) }
        }
        .onChange(of:selection) { _, item in
            guard let item else { return }
            Task { do { guard let data = try await item.loadTransferable(type:Data.self) else { throw NativeAPIError.message("图片内容无法读取。") }; await upload(data) } catch { self.error = NativeSession.readable(error) } }
        }
        .sheet(isPresented:$camera) { NativeCameraPicker { data in camera = false; if let data { Task { await upload(data) } } } }
        .task { do { if preview == nil { preview = try session.local?.imageDraft("image-source-"+purpose) } } catch { self.error = "无法恢复本机照片，原文件已保留。" } }
    }
    @MainActor private func upload(_ source: Data) async {
        guard !uploading else { return }
        uploading = true; error = nil; uploaded = false; preview = source; onUploaded("")
        let owner = session.local?.scope
        defer { uploading = false }
        do {
            let localLimits:NativeJSON = .object(["accepted_content_types":.strings(["image/jpeg"]),"max_dimension":.int(2048),"max_pixels":.int(4_194_304),"max_bytes":.int(5_500_000)])
            let backup = try await Task.detached { try NativeMediaTransfer.jpeg(source,capabilities:localLimits) }.value
            preview = backup
            try session.local?.saveImageDraft("image-source-"+purpose,data:backup)
            let capabilities = try await session.api("media/images/capabilities")
            let data = try await Task.detached { try NativeMediaTransfer.jpeg(backup,capabilities:capabilities) }.value
            preview = data
            try session.local?.saveImageDraft("image-source-"+purpose,data:data)
            guard owner == session.local?.scope else { throw CancellationError() }
            let intent = try await session.api("media/images/upload-intents",method:"POST",body:["purpose":.string(purpose),"content_type":.string("image/jpeg"),"content_length":.int(data.count)])
            guard let url = URL(string:intent["upload_url"].text), url.scheme == "https", intent["method"].text == "PUT" else { throw NativeAPIError.message("上传地址不受支持，请稍后重试。") }
            var request = URLRequest(url:url); request.httpMethod = "PUT"
            for (name,value) in intent["headers"].fields { request.setValue(value.text,forHTTPHeaderField:name) }
            if request.value(forHTTPHeaderField:"Content-Type") == nil { request.setValue("image/jpeg",forHTTPHeaderField:"Content-Type") }
            _ = try await NativeMediaTransfer.perform(request,upload:data)
            let completed = try await session.api("media/images/"+intent["asset_id"].text+"/complete",method:"POST",body:["expected_content_type":.string("image/jpeg"),"expected_content_length":.int(data.count)])
            guard completed["status"].text == "ready" else { throw NativeAPIError.message("图片还未就绪，请重新上传。") }
            guard owner == session.local?.scope else { throw CancellationError() }
            try session.local?.saveDraft("image-source-"+purpose,label:"",value:.null); uploaded = true
            onUploaded(intent["asset_id"].text)
        } catch { self.error = NativeSession.readable(error) }
    }
}

private struct NativeCameraPicker: UIViewControllerRepresentable {
    let onSelect: (Data?) -> Void
    func makeCoordinator() -> Coordinator { Coordinator(onSelect:onSelect) }
    func makeUIViewController(context:Context) -> UIImagePickerController {
        let controller = UIImagePickerController(); controller.sourceType = .camera; controller.delegate = context.coordinator
        return controller
    }
    func updateUIViewController(_ uiViewController:UIImagePickerController,context:Context) {}
    final class Coordinator: NSObject, UINavigationControllerDelegate, UIImagePickerControllerDelegate {
        let onSelect: (Data?) -> Void
        init(onSelect:@escaping (Data?)->Void) { self.onSelect = onSelect }
        func imagePickerControllerDidCancel(_ picker:UIImagePickerController) { onSelect(nil) }
        func imagePickerController(_ picker:UIImagePickerController,didFinishPickingMediaWithInfo info:[UIImagePickerController.InfoKey:Any]) { onSelect((info[.originalImage] as? UIImage)?.jpegData(compressionQuality:0.95)) }
    }
}

struct NativeRemoteImage: View {
    @EnvironmentObject private var session: NativeSession
    let assetID: String
    @State private var image: UIImage?
    @State private var error: String?
    @State private var revision = 0
    var body: some View {
        Group {
            if let image { Image(uiImage:image).resizable().scaledToFit().frame(maxHeight:360).clipShape(RoundedRectangle(cornerRadius:15)) }
            else if let error { VStack { NativeErrorText(message:error); Button("重新加载图片") { revision += 1 } } }
            else { ProgressView("正在读取图片…") }
        }.task(id:"\(assetID)|\(revision)") {
            do {
                let intent = try await session.api("media/images/"+assetID+"/download-intent")
                guard let url = URL(string:intent["download_url"].text), url.scheme == "https" else { throw NativeAPIError.message("图片地址无法读取。") }
                var request = URLRequest(url:url)
                for (name,value) in intent["headers"].fields { request.setValue(value.text,forHTTPHeaderField:name) }
                let data = try await NativeMediaTransfer.perform(request)
                guard let decoded = UIImage(data:data) else { throw NativeAPIError.message("图片内容无法显示。") }
                image = decoded; error = nil
            } catch { self.error = NativeSession.readable(error) }
        }
    }
}

private struct NativePhotoFood: Identifiable {
    let id = UUID()
    var name: String
    var amount: String
    var kcal: String
    var protein: String
    var carbs: String
    var fat: String
    var assumptions: [String]
    init(_ item:NativeJSON) {
        let detected = item["match"]["detected"], nutrition = item["nutrition"]["estimated"]
        name = detected["name"].text; amount = detected["estimated_amount_g"].text
        kcal = nutrition["kcal"].text; protein = nutrition["protein_g"].text; carbs = nutrition["carbs_g"].text; fat = nutrition["fat_g"].text
        assumptions = item["assumptions"].strings + item["follow_up_questions"].strings
    }
    init(saved:NativeJSON) { name = saved["name"].text; amount = saved["amount"].text; kcal = saved["kcal"].text; protein = saved["protein"].text; carbs = saved["carbs"].text; fat = saved["fat"].text; assumptions = saved["assumptions"].strings }
    var snapshot:NativeJSON { .object(["name":.string(name),"amount":.string(amount),"kcal":.string(kcal),"protein":.string(protein),"carbs":.string(carbs),"fat":.string(fat),"assumptions":.strings(assumptions)]) }
    func record() throws -> NativeJSON {
        guard !name.isEmpty, let grams = NativeQuantity.number(amount), grams > 0,
              let k = NativeQuantity.number(kcal), let p = NativeQuantity.number(protein),
              let c = NativeQuantity.number(carbs), let f = NativeQuantity.number(fat),
              [k,p,c,f].allSatisfy({$0 >= 0})
        else { throw NativeAPIError.message("请核对每项食物的名称、份量和营养数值。") }
        let explanation = String(assumptions.joined(separator: "；").prefix(2000))
        return .object(["food_version_id":.null,"name":.string(name),"amount_g":.number(grams),"basis_amount_g":.number(grams),"kcal":.number(k),"protein_g":.number(p),"carbs_g":.number(c),"fat_g":.number(f),"source":.string("model_estimated"),"confidence":.string("low"),"estimate_assumptions": explanation.isEmpty ? .null : .string(explanation)])
    }
    func reviewed() throws -> NativeJSON {
        guard !name.isEmpty, let grams = NativeQuantity.number(amount), grams > 0 else { throw NativeAPIError.message("请填写食物名称和有效份量。") }
        return .object(["name":.string(name),"estimated_amount_g":.number(grams),"amount_min_g":.number(grams),"amount_max_g":.number(grams),"confidence":.string("high"),"portion_confidence":.string("high"),"portion_basis":.string("用户核对份量"),"visual_evidence":.null])
    }
}

struct NativeNutritionPhotoView: View {
    @EnvironmentObject private var session: NativeSession
    let initialMeal: String
    let initialDate: Date?
    let onUseEstimate: (([NativeJSON]) -> Void)?
    @State private var assetID = ""
    @State private var meal: String
    @State private var eatenAt: Date
    @State private var notes = ""
    @State private var draft: NativeJSON = .null
    @State private var foods: [NativePhotoFood] = []
    @State private var saved = false
    @State private var initialized = false

    init(initialMeal: String = "lunch", initialDate: Date? = nil, onUseEstimate: (([NativeJSON]) -> Void)? = nil) {
        self.initialMeal = initialMeal
        self.initialDate = initialDate
        self.onUseEstimate = onUseEstimate
        _meal = State(initialValue: initialMeal)
        _eatenAt = State(initialValue: initialDate ?? .now)
    }

    private var draftKey: String {
        guard onUseEstimate != nil, let initialDate else { return "nutrition-photo" }
        return "nutrition-photo-add-" + NativeDates.day(initialDate) + "-" + initialMeal
    }

    private var needsUpdate: Bool {
        guard !draft.isNull else { return false }
        if notes != draft["notes"].text { return true }
        let estimated = draft["calculation"]["items"].values.map { NativePhotoFood($0) }
        return foods.contains { food in
            !estimated.contains { $0.name == food.name && NativeQuantity.number($0.amount) == NativeQuantity.number(food.amount) }
        }
    }

    private var totals: [Double]? {
        guard !foods.isEmpty, !needsUpdate else { return nil }
        let fields = [\NativePhotoFood.kcal, \.carbs, \.protein, \.fat]
        let result = fields.compactMap { field -> Double? in
            let values = foods.compactMap { NativeQuantity.number($0[keyPath: field]) }
            return values.count == foods.count ? values.reduce(0, +) : nil
        }
        return result.count == fields.count && result.allSatisfy(\.isFinite) ? result : nil
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 15) {
                NativeImageSelector(purpose: "nutrition_entry") { id in
                    assetID = id
                    draft = .null
                    foods = []
                    saved = false
                }
                options
                if let totals { NativeMealTotalCard(values: totals, estimated: true) }
                ForEach($foods) { $food in
                    let id = food.id
                    NativePhotoFoodEditor(food: $food) { foods.removeAll { $0.id == id } }
                }
                if needsUpdate {
                    Label("核对信息已调整，请重新估算。", systemImage: "arrow.clockwise")
                        .font(.footnote).foregroundStyle(NativeTheme.muted)
                }
                if !recognitionNotes.isEmpty {
                    DisclosureGroup("估算说明") {
                        ForEach(recognitionNotes, id: \.self) { Text($0).font(.footnote).padding(.top, 4) }
                    }
                }
                if !assetID.isEmpty && !saved && (draft.isNull || needsUpdate || foods.isEmpty) {
                    NativeActionButton(title: foods.isEmpty ? "估算这餐" : "按调整后的份量重新估算", action: estimate)
                }
                if totals != nil && !saved {
                    NativeActionButton(title: onUseEstimate == nil ? "确认保存这餐" : "加入这餐", action: save)
                }
                if saved { Label("这餐已保存", systemImage: "checkmark.circle.fill").foregroundStyle(.green) }
            }.nativePage()
        }
        .background(NativeTheme.background)
        .scrollDismissesKeyboard(.interactively)
        .navigationTitle("AI 拍照估算")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            guard !initialized else { return }
            initialized = true
            if initialDate == nil {
                eatenAt = NativeDates.day(session.selectedDate) == NativeDates.day() ? .now : session.selectedDate
            }
        }
        .nativeDraft(draftKey, label: "拍照饮食核对", value: snapshot) { value in
            initialized = true
            assetID = value["image"].text
            meal = value["meal"].text
            eatenAt = NativeDates.parse(value["time"].text) ?? initialDate ?? .now
            notes = value["notes"].text
            draft = value["draft"]
            foods = value["foods"].values.map { NativePhotoFood(saved: $0) }
        }
    }

    private var options: some View {
        NativeCard {
            DisclosureGroup("补充食物或份量") {
                VStack(alignment: .leading, spacing: 10) {
                    if onUseEstimate == nil {
                        NativeMealPicker(selection: $meal)
                        DatePicker("进食时间", selection: $eatenAt).environment(\.timeZone, NativeDates.china)
                    }
                    NativeField(title: "食物、配料、实际克数", text: $notes)
                }.padding(.top, 8)
            }.font(.subheadline)
        }
        .disabled(saved)
    }

    private func estimate(_ key: String) async throws {
        guard !assetID.isEmpty else { throw NativeAPIError.message("请先上传餐食照片。") }
        let input = snapshot
        var body: [String: NativeJSON] = [
            "image_asset_id": .string(assetID), "meal_type": .string(initialDate == nil ? meal : initialMeal),
            "eaten_at": .string(NativeDates.timestamp(initialDate ?? eatenAt)),
            "notes": notes.isEmpty ? .null : .string(notes)
        ]
        if !foods.isEmpty { body["reviewed_foods"] = .array(try foods.map { try $0.reviewed() }) }
        let response = try await session.api("nutrition/entry-drafts:estimate-image", method: "POST", body: body, key: key)
        guard input == snapshot else { return }
        let recognized = response["calculation"]["items"].values.map { NativePhotoFood($0) }
        guard !recognized.isEmpty else { throw NativeAPIError.message("暂未识别出可用的食物，请换张照片再试。") }
        draft = response
        foods = recognized
    }

    private func save(_ key: String) async throws {
        guard !foods.isEmpty, !needsUpdate else { throw NativeAPIError.message("请先核对食物与克数。") }
        let items = try foods.map { try $0.record() }
        if let onUseEstimate {
            try session.local?.saveDraft(draftKey, label: "拍照饮食核对", value: .null)
            onUseEstimate(items)
            return
        }
        _ = try await session.api("nutrition/entries", method: "POST", body: [
            "meal_type": .string(meal), "eaten_at": .string(NativeDates.timestamp(eatenAt)),
            "items": .array(items), "is_flexible_meal": .bool(false),
            "notes": .string("AI 照片估算，经用户核对；图片 ID：" + assetID)
        ], key: key, draftKey: draftKey)
        saved = true
        await session.reload()
    }

    private var recognitionNotes: [String] {
        draft["recognition"]["assumptions"].strings + draft["recognition"]["follow_up_questions"].strings
    }

    private var snapshot: NativeJSON {
        .object(["image": .string(assetID), "meal": .string(meal), "time": .string(NativeDates.timestamp(eatenAt)),
                 "notes": .string(notes), "draft": draft, "foods": .array(foods.map(\.snapshot))])
    }
}

private struct NativePhotoFoodEditor: View {
    @Binding var food: NativePhotoFood
    let remove: () -> Void

    var body: some View {
        NativeCard {
            HStack(spacing: 10) {
                NativeActionIcon(symbol: "fork.knife", tint: AppTab.meals.tint)
                VStack(alignment: .leading, spacing: 4) {
                    Text(food.name).font(.headline)
                    Text(food.amount + " 克 · 估算 " + food.kcal + " 千卡").font(.caption).foregroundStyle(NativeTheme.muted)
                }
                Spacer(minLength: 5)
                Button(role: .destructive, action: remove) {
                    Image(systemName: "xmark.circle").frame(width: 44, height: 44)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("移除" + food.name)
            }
            DisclosureGroup("调整识别结果") {
                VStack(spacing: 8) {
                    NativeField(title: "食品名称", text: $food.name)
                    NativeField(title: "实际份量（克）", text: $food.amount, keyboard: .decimalPad)
                }.padding(.top, 8)
            }.font(.subheadline)
        }
    }
}
