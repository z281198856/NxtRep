import SwiftUI

struct NativeProfileView: View {
    @EnvironmentObject private var session: NativeSession
    var body: some View {
        List {
            Section {
                Label(session.user?.username ?? "",systemImage:"person.crop.circle.fill").font(.title3.weight(.semibold))
                Text(session.serverText).font(.caption).foregroundStyle(NativeTheme.muted).textSelection(.enabled)
            }
            Section("账户与偏好") {
                NavigationLink("个人资料") { NativePersonalProfileForm() }
                NavigationLink("训练目标与偏好") { NativeTrainingPreferencesForm() }
                NavigationLink("应用与隐私") { NativeAppSettingsForm() }
                NavigationLink("账户安全与登录设备") { NativeAccountSecurityView() }
                NavigationLink("离线记录与草稿") { NativeLocalRecordsView() }
            }
            Section("教练与提醒") {
                NavigationLink("AI 草稿、确认与记忆") { NativeAgentManagementView() }
                NavigationLink("主动教练与提醒设置") { NativeCoachSettingsView() }
                NavigationLink("本机系统提醒") { NativeReminderSettingsView() }
            }
            Section {
                LabeledContent("App 版本",value:(Bundle.main.object(forInfoDictionaryKey:"CFBundleShortVersionString") as? String) ?? "")
                Button("退出登录",role:.destructive) { Task { await session.logout() } }
            }
        }.navigationTitle("我的")
    }
}

struct NativePersonalProfileForm: View {
    @EnvironmentObject private var session: NativeSession
    @Environment(\.dismiss) private var dismiss
    @State private var current: NativeJSON = .null
    @State private var name = ""
    @State private var sex = "unspecified"
    @State private var birthday = Date()
    @State private var hasBirthday = false
    @State private var height = ""
    @State private var weight = ""
    @State private var experience = "beginner"
    @State private var duration = 45
    @State private var error: String?
    var body: some View {
        Form {
            NativeErrorText(message:error)
            NativeField(title:"昵称",text:$name)
            Picker("性别",selection:$sex) { Text("男").tag("male"); Text("女").tag("female"); Text("其他").tag("other"); Text("不填写").tag("unspecified") }
            Toggle("填写出生日期",isOn:$hasBirthday)
            if hasBirthday { DatePicker("出生日期",selection:$birthday,in:...Date(),displayedComponents:.date) }
            NativeField(title:"身高（\(session.lengthUnit)，可留空）",text:$height,keyboard:.decimalPad)
            NativeField(title:"体重（\(session.weightUnit)，可留空）",text:$weight,keyboard:.decimalPad)
            Picker("训练经验",selection:$experience) { Text("新手").tag("beginner"); Text("有训练基础").tag("intermediate"); Text("进阶").tag("advanced") }
            Stepper("每次训练约 \(duration) 分钟",value:$duration,in:5...300,step:5)
            NativeActionButton(title:"保存个人资料") { _ in
                guard !current.isNull, (height.isEmpty || (Double(height) ?? -1) > 0), (weight.isEmpty || (Double(weight) ?? -1) > 0) else { throw NativeAPIError.message("请填写有效身高和体重，或将其留空。") }
                var body: [String:NativeJSON] = ["display_name":name.isEmpty ? .null : .string(name),"sex":.string(sex),"birth_date":hasBirthday ? .string(NativeDates.day(birthday)) : .null,"height_cm":height.isEmpty ? .null : .number(session.toCM(Double(height)!)),"experience_level":.string(experience),"session_duration_minutes":.int(duration),"expected_version":.int(current.version)]
                if !weight.isEmpty, session.toKG(Double(weight)!) != current["weight_kg"].double { body["weight_kg"] = .number(session.toKG(Double(weight)!)) }
                _ = try await session.api("profile",method:"PATCH",body:body)
                dismiss()
            }.disabled(current.isNull)
        }.navigationTitle("个人资料")
            .task {
                do {
                    current = try await session.api("profile")
                    name = current["display_name"].text; sex = current["sex"].text
                    hasBirthday = !current["birth_date"].isNull; birthday = NativeDates.parse(current["birth_date"].text) ?? .now
                    height = current["height_cm"].isNull ? "" : session.displayLength(current["height_cm"].double).formatted(.number.precision(.fractionLength(0...2)))
                    weight = current["weight_kg"].isNull ? "" : session.displayWeight(current["weight_kg"].double).formatted(.number.precision(.fractionLength(0...3)))
                    experience = current["experience_level"].text.isEmpty ? "beginner" : current["experience_level"].text
                    duration = max(5,current["session_duration_minutes"].integer)
                } catch { self.error = NativeSession.readable(error) }
            }
    }
}

struct NativeTrainingPreferencesForm: View {
    @EnvironmentObject private var session: NativeSession
    @Environment(\.dismiss) private var dismiss
    @State private var profile: NativeJSON = .null
    @State private var preferences: NativeJSON = .null
    @State private var goal = "muscle_gain"
    @State private var days = 3
    @State private var equipment: Set<String> = []
    @State private var error: String?
    var body: some View {
        Form {
            NativeErrorText(message:error)
            Section("目标与频率") {
                NativeGoalPicker(selection:$goal)
                Stepper("每周 \(days) 天",value:$days,in:1...7)
            }
            Section("可用器械") { NativeEquipmentToggles(selection:$equipment) }
            NativeActionButton(title:"检查并保存训练偏好") { _ in
                guard !profile.isNull, !preferences.isNull, !equipment.isEmpty else { throw NativeAPIError.message("请至少选择一种训练条件。") }
                let constraints = preferences["constraints"]
                let body: [String:NativeJSON] = ["goal_type":.string(goal),"target_date":preferences["goal"]["target_date"],"target_weight_kg":preferences["goal"]["target_weight_kg"],"equipment":.strings(equipment.sorted()),"preferred_exercises":constraints["preferred_exercises"],"disliked_exercises":constraints["disliked_exercises"],"pain_or_injuries":constraints["pain_or_injuries"],"allergies":constraints["allergies"],"dietary_preferences":constraints["dietary_preferences"],"expected_version":.int(preferences.version)]
                let check = try await session.api("profile/goal-check",method:"POST",body:body)
                guard check["valid"].flag else { throw NativeAPIError.message("目标与训练条件存在冲突，请调整后再保存。") }
                preferences = try await session.api("profile/goals-and-constraints",method:"PUT",body:body)
                profile = try await session.api("profile",method:"PATCH",body:["weekly_training_days":.int(days),"expected_version":.int(profile.version)])
                dismiss()
            }.disabled(profile.isNull || preferences.isNull)
        }.navigationTitle("训练目标与偏好")
            .task {
                do {
                    profile = try await session.api("profile"); preferences = try await session.api("profile/goals-and-constraints")
                    goal = preferences["goal"]["goal_type"].text; days = max(1,profile["weekly_training_days"].integer); equipment = Set(preferences["constraints"]["equipment"].strings)
                } catch { self.error = NativeSession.readable(error) }
            }
    }
}

struct NativeGoalPicker: View {
    @Binding var selection: String
    var body: some View { Picker("训练目标",selection:$selection) { Text("增肌塑形").tag("muscle_gain"); Text("减脂保肌").tag("fat_loss_retain"); Text("提升力量").tag("strength") } }
}

struct NativeEquipmentToggles: View {
    @Binding var selection: Set<String>
    var body: some View {
        ForEach(["bodyweight","dumbbell","barbell","machine","smith_machine","cable","kettlebell","band"],id:\.self) { code in
            Toggle(NativeLabels.tool(code),isOn:Binding(get:{selection.contains(code)},set:{if $0 {selection.insert(code)} else {selection.remove(code)}}))
        }
    }
}

struct NativeOnboardingView: View {
    @EnvironmentObject private var session: NativeSession
    @State private var goal = "muscle_gain"
    @State private var days = 3
    @State private var equipment: Set<String> = ["bodyweight"]
    @State private var pain = ""
    var body: some View {
        NavigationStack {
            Form {
                Section("先了解你的训练条件") { NativeGoalPicker(selection:$goal); Stepper("每周 \(days) 天",value:$days,in:1...7) }
                Section("可用器械") { NativeEquipmentToggles(selection:$equipment) }
                Section("当前疼痛部位（可选）") { TextField("没有可留空",text:$pain) }
                NativeActionButton(title:"保存并进入 NxtRep") { _ in
                    guard !equipment.isEmpty else { throw NativeAPIError.message("请选择至少一种训练条件。") }
                    let profile = try await session.api("profile")
                    var body: [String:NativeJSON] = ["goal_type":.string(goal),"target_date":.null,"target_weight_kg":.null,"equipment":.strings(equipment.sorted()),"preferred_exercises":.array([]),"disliked_exercises":.array([]),"pain_or_injuries":pain.isEmpty ? .array([]) : .array([.object(["kind":.string("current_pain"),"body_part":.string(pain),"severity":.null,"notes":.null])]),"allergies":.array([]),"dietary_preferences":.array([])]
                    do { let old = try await session.api("profile/goals-and-constraints"); body["expected_version"] = .int(old.version) }
                    catch NativeAPIError.response(_,let code) where code == "GOALS_NOT_FOUND" { }
                    _ = try await session.api("profile/goals-and-constraints",method:"PUT",body:body)
                    _ = try await session.api("profile",method:"PATCH",body:["weekly_training_days":.int(days),"experience_level":profile["experience_level"].isNull ? .string("beginner") : profile["experience_level"],"expected_version":.int(profile.version)])
                    try await session.loadAccountAndSettings()
                }
                Button("退出登录",role:.destructive) { Task { await session.logout() } }
            }.navigationTitle("设置训练目标")
        }
    }
}

struct NativeAppSettingsForm: View {
    @EnvironmentObject private var session: NativeSession
    @Environment(\.dismiss) private var dismiss
    @State private var units = "metric"
    @State private var privacy = "private"
    @State private var analytics = false
    var body: some View {
        Form {
            Section("显示单位") { Picker("单位制",selection:$units) { Text("公制（kg / cm）").tag("metric"); Text("英制（lb / in）").tag("imperial") } }
            Section("首页提醒隐私") {
                Picker("显示内容",selection:$privacy) { Text("隐藏摘要").tag("private"); Text("显示摘要").tag("summary") }
                Text("隐藏摘要时，首页只提示有新提醒；主动打开提醒列表后仍可查看详情。").font(.caption).foregroundStyle(NativeTheme.muted)
            }
            Toggle("允许匿名使用分析",isOn:$analytics)
            NativeActionButton(title:"保存应用设置") { _ in
                let result = try await session.api("settings",method:"PATCH",body:["unit_system":.string(units),"privacy_mode":.string(privacy),"share_anonymous_analytics":.bool(analytics),"expected_version":.int(session.settings.version)])
                session.applySettings(result); dismiss()
            }
        }.navigationTitle("应用与隐私")
            .onAppear { units = session.settings["unit_system"].text; privacy = session.settings["privacy_mode"].text; analytics = session.settings["share_anonymous_analytics"].flag }
    }
}

struct NativeAccountSecurityView: View {
    @EnvironmentObject private var session: NativeSession
    @StateObject private var resource = NativeResource()
    @State private var old = ""
    @State private var password = ""
    @State private var repeatPassword = ""
    @State private var revision = 0
    @State private var revokeID = ""
    @State private var revokeAll = false
    @State private var error: String?
    @State private var changed = false
    var body: some View {
        Form {
            Section("修改密码") {
                SecureField("当前密码",text:$old).textContentType(.password)
                SecureField("新密码（8–128 个字符）",text:$password).textContentType(.newPassword)
                SecureField("再次输入新密码",text:$repeatPassword).textContentType(.newPassword)
                NativeActionButton(title:"修改密码并撤销旧登录") { _ in
                    guard (8...128).contains(password.count), password == repeatPassword, password != old else { throw NativeAPIError.message("新密码需为 8–128 个字符、两次输入一致，且不同于当前密码。") }
                    try await session.changePassword(current:old,new:password)
                    old = ""; password = ""; repeatPassword = ""; changed = true; revision += 1
                }
                if changed { Text("密码已修改，当前设备已保留新登录。").foregroundStyle(.green) }
            }
            Section("登录设备") {
                NativeErrorText(message:resource.error ?? error)
                ForEach(resource.value["sessions"].values,id:\.id) { item in
                    VStack(alignment:.leading,spacing:7) {
                        Text(item["device_name"].text.isEmpty ? "未命名设备" : item["device_name"].text).font(.headline)
                        Text("登录于 "+NativeDates.display(item["created_at"].text)).font(.caption)
                        if item["is_current"].flag { Label("当前设备",systemImage:"checkmark.shield").font(.caption).foregroundStyle(.green) }
                        else { Button("撤销此设备登录",role:.destructive) { revokeID = item.id } }
                    }
                }
                Button("撤销其他所有设备登录",role:.destructive) { revokeAll = true }
            }
        }.navigationTitle("账户安全")
            .task(id:revision) { await resource.load { try await session.api("auth/sessions") } }
            .confirmationDialog("撤销选中设备登录？",isPresented:Binding(get:{!revokeID.isEmpty},set:{if !$0 {revokeID = ""}}),titleVisibility:.visible) {
                Button("确认撤销",role:.destructive) { let id = revokeID; Task { do { _ = try await session.api("auth/sessions/"+id,method:"DELETE"); revision += 1 } catch { self.error = NativeSession.readable(error) } }; revokeID = "" }
            }
            .confirmationDialog("保留当前设备，并撤销其他全部设备的登录？",isPresented:$revokeAll,titleVisibility:.visible) {
                Button("撤销其他登录",role:.destructive) { Task { do { _ = try await session.api("auth/sessions/revoke-others",method:"POST"); revision += 1 } catch { self.error = NativeSession.readable(error) } } }
            }
    }
}

struct NativePasswordSetupView: View {
    @EnvironmentObject private var session: NativeSession
    @State private var username = ""
    @State private var setupToken = ""
    @State private var password = ""
    @State private var repeatPassword = ""
    var body: some View {
        Form {
            Text("使用管理员提供的 NxtRep 账号和首次设密凭据。").font(.subheadline).foregroundStyle(NativeTheme.muted)
            NativeField(title:"服务器地址",text:$session.serverText,keyboard:.URL)
            NativeField(title:"NxtRep 账号",text:$username)
            SecureField("首次设密凭据",text:$setupToken)
            SecureField("设置密码",text:$password).textContentType(.newPassword)
            SecureField("再次输入密码",text:$repeatPassword).textContentType(.newPassword)
            NativeActionButton(title:"设置密码并登录") { _ in
                guard password == repeatPassword, (8...128).contains(password.count) else { throw NativeAPIError.message("请填写一致的 8–128 位密码。") }
                try await session.setupPassword(username:username,setupToken:setupToken,password:password)
                setupToken = ""; password = ""; repeatPassword = ""
            }
        }.navigationTitle("首次设置密码")
    }
}
