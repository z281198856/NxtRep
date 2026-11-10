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
        .task { let saved = session.local?.draft("image-source-"+purpose)["value"]["bytes"].text ?? ""; if preview == nil,!saved.isEmpty { preview = Data(base64Encoded:saved) } }
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
            try session.local?.saveDraft("image-source-"+purpose,label:"待上传照片",value:.object(["bytes":.string(backup.base64EncodedString())]))
            let capabilities = try await session.api("media/images/capabilities")
            let data = try await Task.detached { try NativeMediaTransfer.jpeg(backup,capabilities:capabilities) }.value
            preview = data
            try session.local?.saveDraft("image-source-"+purpose,label:"待上传照片",value:.object(["bytes":.string(data.base64EncodedString())]))
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
        guard !name.isEmpty, let grams = Double(amount), grams > 0, let k = Double(kcal), let p = Double(protein), let c = Double(carbs), let f = Double(fat), [k,p,c,f].allSatisfy({$0 >= 0}) else { throw NativeAPIError.message("请核对每项食物的名称、份量和营养数值。") }
        return .object(["food_version_id":.null,"name":.string(name),"amount_g":.number(grams),"basis_amount_g":.number(grams),"kcal":.number(k),"protein_g":.number(p),"carbs_g":.number(c),"fat_g":.number(f),"source":.string("model_estimated"),"confidence":.string("low")])
    }
    func reviewed() throws -> NativeJSON {
        guard !name.isEmpty, let grams = Double(amount), grams > 0 else { throw NativeAPIError.message("请填写食物名称和有效份量。") }
        return .object(["name":.string(name),"estimated_amount_g":.number(grams),"amount_min_g":.number(grams),"amount_max_g":.number(grams),"confidence":.string("high"),"portion_confidence":.string("high"),"portion_basis":.string("用户核对份量"),"visual_evidence":.null])
    }
}

struct NativeNutritionPhotoView: View {
    @EnvironmentObject private var session: NativeSession
    @State private var assetID = ""
    @State private var meal = "lunch"
    @State private var eatenAt = Date()
    @State private var notes = ""
    @State private var draft: NativeJSON = .null
    @State private var foods: [NativePhotoFood] = []
    @State private var checked = false
    @State private var saved = false
    var body: some View {
        ScrollView {
            VStack(alignment:.leading,spacing:16) {
                NativeImageSelector(purpose:"nutrition_entry") { assetID = $0; draft = .null; foods = []; checked = false; saved = false }
                NativeMealPicker(selection:$meal)
                DatePicker("进食时间",selection:$eatenAt)
                NativeField(title:"补充食物、配料或份量信息",text:$notes)
                NativeActionButton(title:foods.isEmpty ? "估算这餐" : "按核对内容重新估算") { _ in
                    guard !assetID.isEmpty else { throw NativeAPIError.message("请先上传餐食照片。") }
                    var body: [String:NativeJSON] = ["image_asset_id":.string(assetID),"meal_type":.string(meal),"eaten_at":.string(NativeDates.timestamp(eatenAt)),"notes":notes.isEmpty ? .null : .string(notes)]
                    if !foods.isEmpty { body["reviewed_foods"] = .array(try foods.map { try $0.reviewed() }) }
                    let result = try await session.api("nutrition/entry-drafts:estimate-image",method:"POST",body:body)
                    draft = result; foods = result["calculation"]["items"].values.map { NativePhotoFood($0) }; checked = false
                }
                if !draft.isNull {
                    Text("照片估算需核对，不能作为精确测量。").font(.subheadline).foregroundStyle(.orange)
                    ForEach(recognitionNotes,id:\.self) { Text($0).font(.caption).foregroundStyle(NativeTheme.muted) }
                    ForEach($foods) { $food in
                        NativePhotoFoodEditor(food:$food) { foods.removeAll {$0.id == food.id}; checked = false }
                    }
                    Toggle("我已核对食物、份量和对应营养数值",isOn:$checked)
                    NativeActionButton(title:"确认保存饮食记录") { key in
                        guard checked, !foods.isEmpty else { throw NativeAPIError.message("请先逐项核对估算结果。") }
                        _ = try await session.api("nutrition/entries",method:"POST",body:["meal_type":.string(meal),"eaten_at":.string(NativeDates.timestamp(eatenAt)),"items":.array(try foods.map { try $0.record() }),"is_flexible_meal":.bool(false),"notes":.string("AI 照片估算，经用户核对；图片 ID："+assetID)],key:key,draftKey:"nutrition-photo")
                        saved = true; await session.reload()
                    }.disabled(!checked || saved)
                    if saved { Label("这餐已保存",systemImage:"checkmark.circle.fill").foregroundStyle(.green) }
                }
            }.nativePage()
        }.navigationTitle("拍照记一餐").onAppear { eatenAt = session.selectedDate }
            .nativeDraft("nutrition-photo",label:"拍照饮食核对",value:photoSnapshot) { v in assetID = v["image"].text; meal = v["meal"].text; eatenAt = NativeDates.parse(v["time"].text) ?? .now; notes = v["notes"].text; draft = v["draft"]; foods = v["foods"].values.map { NativePhotoFood(saved:$0) }; checked = false; saved = false }
            .onChange(of:foodFingerprint) { _,_ in checked = false; saved = false }
    }
    private var recognitionNotes: [String] { draft["recognition"]["assumptions"].strings + draft["recognition"]["follow_up_questions"].strings }
    private var photoSnapshot:NativeJSON { .object(["image":.string(assetID),"meal":.string(meal),"time":.string(NativeDates.timestamp(eatenAt)),"notes":.string(notes),"draft":draft,"foods":.array(foods.map(\.snapshot))]) }
    private var foodFingerprint: String { foods.map { [$0.name,$0.amount,$0.kcal,$0.protein,$0.carbs,$0.fat].joined(separator:"|") }.joined(separator:";") }
}

private struct NativePhotoFoodEditor: View {
    @Binding var food: NativePhotoFood
    let remove: () -> Void
    var body: some View {
        NativeCard {
            NativeField(title:"食品名称",text:$food.name)
            NativeField(title:"份量（克）",text:$food.amount,keyboard:.decimalPad)
            NativeField(title:"该份量热量（千卡）",text:$food.kcal,keyboard:.decimalPad)
            NativeField(title:"蛋白质（克）",text:$food.protein,keyboard:.decimalPad)
            NativeField(title:"碳水（克）",text:$food.carbs,keyboard:.decimalPad)
            NativeField(title:"脂肪（克）",text:$food.fat,keyboard:.decimalPad)
            ForEach(food.assumptions,id:\.self) { Text($0).font(.caption).foregroundStyle(NativeTheme.muted) }
            Button("移除此项",role:.destructive,action:remove)
        }
    }
}
