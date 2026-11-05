import SwiftUI

enum AppTab: String, CaseIterable, Identifiable {
    case today, plan, meals, progress, coach, account

    var id: String { rawValue }

    var title: String {
        switch self {
        case .today: "首页"
        case .plan: "计划"
        case .meals: "饮食"
        case .progress: "进展"
        case .coach: "AI 教练"
        case .account: "我的"
        }
    }

    var heading: String {
        switch self {
        case .today: "今日"
        case .coach: "AI 私人教练"
        default: title
        }
    }

    var accessibilityTitle: String { self == .coach ? heading : title }

    var icon: String {
        switch self {
        case .today: "house"
        case .plan: "dumbbell"
        case .meals: "fork.knife"
        case .progress: "chart.line.uptrend.xyaxis"
        case .coach: "bubble.left.and.text.bubble.right"
        case .account: "person"
        }
    }

    var tint: Color {
        switch self {
        case .today: NativeTheme.accent
        case .plan: NativeTheme.color(0x9A5E27)
        case .meals: NativeTheme.color(0x2C715C)
        case .progress: NativeTheme.color(0x3C67A7)
        case .coach: NativeTheme.color(0x7555A2)
        case .account: NativeTheme.color(0x596586)
        }
    }
}

enum FeatureAction {
    case detail, freeWorkout, water, coach
}

struct DemoFeature: Identifiable {
    struct Row: Identifiable {
        let label: String
        let value: String

        var id: String { label }
    }

    let id: String
    let title: String
    let subtitle: String
    let icon: String
    let tint: Color
    let action: FeatureAction
    let rows: [Row]
    let quickTitle: String?
    let showsPhotoPicker: Bool

    init(
        _ id: String,
        _ title: String,
        _ subtitle: String,
        tab: AppTab,
        icon: String? = nil,
        tint: Color? = nil,
        action: FeatureAction = .detail,
        rows: [(String, String)] = [],
        quickTitle: String? = nil,
        showsPhotoPicker: Bool = false
    ) {
        self.id = id
        self.title = title
        self.subtitle = subtitle
        self.icon = icon ?? tab.icon
        self.tint = tint ?? tab.tint
        self.action = action
        self.rows = rows.map { Row(label: $0.0, value: $0.1) }
        self.quickTitle = quickTitle
        self.showsPhotoPicker = showsPhotoPicker
    }
}

enum DemoContent {
    static let quickEntries = [free, exercise, photoMeal, foods, body, ask]

    static func entries(for tab: AppTab) -> [DemoFeature] {
        switch tab {
        case .today: quickEntries
        case .plan: [week, planBuilder, recommended, exercise, history, free]
        case .meals: [photoMeal, foods, manualMeal, drink, mealTools]
        case .progress: [body, bodyFat, trend, records, bodyPhoto, report]
        case .coach: [chat, conversation, memory, coachPhoto, draft, coachReminders]
        case .account: [profile, preferences, privacy, security, offline, reminders]
        }
    }

    static let trainingOverview = DemoFeature(
        "trainingOverview", "训练概览", "本周已完成 2 次训练",
        tab: .progress,
        rows: [("本周训练", "完成 2 / 3 次"), ("已记录组数", "12 组")]
    )

    private static let free = DemoFeature(
        "free", "自主训练", "按自己的节奏选动作和记组",
        tab: .plan, action: .freeWorkout
    )

    private static let exercise = DemoFeature(
        "exercise", "动作库", "按部位和器械浏览动作",
        tab: .plan,
        rows: [("杠铃卧推", "胸部 · 杠铃"), ("高位下拉", "背部 · 绳索"), ("杯式深蹲", "腿部 · 哑铃")]
    )

    private static let photoMeal = DemoFeature(
        "photoMeal", "拍照记一餐", "选择餐食照片并核对估算",
        tab: .meals, icon: "camera",
        rows: [("照片来源", "从相册选择"), ("估算内容", "食品、份量与营养素"), ("记录前", "核对并确认")],
        showsPhotoPicker: true
    )

    private static let foods = DemoFeature(
        "foods", "食品库", "浏览每 100 克的营养数据",
        tab: .meals,
        rows: [("熟米饭", "130 千卡 / 100 克"), ("鸡胸肉", "165 千卡 / 100 克"), ("鸡蛋", "143 千卡 / 100 克")]
    )

    private static let body = DemoFeature(
        "body", "记体重 / 体脂", "查看身体记录与测量入口",
        tab: .progress,
        rows: [("最近一次体重", "72.4 kg"), ("最近一次体脂率", "18.6%"), ("记录方式", "日期、数值和备注")],
        quickTitle: "身体数据"
    )

    private static let ask = DemoFeature(
        "ask", "问 AI 教练", "训练、饮食与恢复建议",
        tab: .coach, action: .coach
    )

    private static let week = DemoFeature(
        "week", "本周安排", "查看训练日和恢复日",
        tab: .plan, icon: "calendar",
        rows: [("本周第 1 次", "全身训练 · 已完成"), ("本周第 2 次", "下肢训练 · 已完成"), ("今日", "上肢力量 · 待开始")]
    )

    private static let planBuilder = DemoFeature(
        "planBuilder", "自定义训练计划", "智能生成、文字导入和手动编排",
        tab: .plan, icon: "list.bullet.rectangle",
        rows: [("智能生成", "根据目标、时间和器械生成草稿"), ("文字导入", "把已有计划拆成动作和组数"), ("手动编排", "添加训练日和动作")]
    )

    private static let recommended = DemoFeature(
        "recommended", "推荐计划", "浏览可按目标选择的计划",
        tab: .plan, icon: "calendar",
        rows: [("全身基础", "每周 3 次"), ("上下肢分化", "每周 4 次")]
    )

    private static let history = DemoFeature(
        "history", "训练历史", "按训练日回看动作和组数",
        tab: .plan, icon: "clock.arrow.circlepath",
        rows: [("最近一次", "下肢训练 · 7 组"), ("上一次", "全身训练 · 5 组")]
    )

    private static let manualMeal = DemoFeature(
        "manualMeal", "手动填写", "按餐次记录食品与营养",
        tab: .meals, icon: "square.and.pencil",
        rows: [("餐次", "晚餐"), ("可填写", "热量、碳水、蛋白质、脂肪"), ("示例", "米饭 150 克、鸡蛋 1 个")]
    )

    private static let drink = DemoFeature(
        "drink", "饮水记录", "查看当天累计或快速记一杯",
        tab: .meals, icon: "drop", tint: NutrientKind.water.labelColor, action: .water
    )

    private static let mealTools = DemoFeature(
        "mealTools", "饮食工具", "管理食谱和复用餐次",
        tab: .meals, icon: "book.closed",
        rows: [
            ("我的食谱", "查看常吃组合"), ("复制上一餐", "选择餐次后核对份量"),
            ("补记昨天", "先选择日期和餐次"), ("自由餐安排", "查看计划与记录")
        ]
    )

    private static let bodyFat = DemoFeature(
        "bodyFat", "围度估算体脂", "通过测量数据生成估算",
        tab: .progress, icon: "ruler",
        rows: [("输入项目", "身高、颈围和腰围等"), ("结果", "估算体脂率"), ("记录方式", "核对后记录并查看趋势")]
    )

    private static let trend = DemoFeature(
        "trend", "身体趋势与记录", "回看体重和体脂变化",
        tab: .progress,
        rows: [("上次", "73.0 kg · 19.0%"), ("本次", "72.4 kg · 18.6%"), ("体重变化", "−0.6 kg")]
    )

    private static let records = DemoFeature(
        "records", "个人纪录", "查看动作重量和次数的里程碑",
        tab: .progress, icon: "medal",
        rows: [("杠铃卧推", "60 kg × 6 次"), ("杯式深蹲", "24 kg × 10 次")]
    )

    private static let bodyPhoto = DemoFeature(
        "bodyPhoto", "照片记录与 AI 评估", "按日期整理身体进度照片",
        tab: .progress, icon: "camera",
        rows: [("照片记录", "按日期和角度查看"), ("AI 评估", "选取照片并核对说明")],
        showsPhotoPicker: true
    )

    private static let report = DemoFeature(
        "report", "阶段报告", "回顾训练、饮食和身体变化",
        tab: .progress, icon: "doc.text",
        rows: [("训练", "本周完成 2 / 3 次"), ("已记录组数", "12 组"), ("身体趋势", "参见身体记录")]
    )

    private static let chat = DemoFeature(
        "chat", "新建对话", "向教练提问或添加照片",
        tab: .coach,
        rows: [("示例问题", "今天的卧推应该怎么安排？"), ("上下文", "今日训练计划")]
    )

    private static let conversation = DemoFeature(
        "conversation", "历史对话", "回看对话及已归档内容",
        tab: .coach, icon: "clock.arrow.circlepath",
        rows: [("今日", "上肢训练安排"), ("最近", "一周饮食回顾"), ("已归档", "查看归档会话")]
    )

    private static let memory = DemoFeature(
        "memory", "长期记忆", "查看教练记住的偏好",
        tab: .coach, icon: "bookmark",
        rows: [("训练时间", "工作日晚上"), ("常用器械", "杠铃与哑铃"), ("管理", "可添加、编辑或移除")]
    )

    private static let coachPhoto = DemoFeature(
        "coachPhoto", "给教练发照片", "从相册选择用于提问的照片",
        tab: .coach, icon: "camera",
        rows: [("示例用途", "结合餐食照片提问")],
        showsPhotoPicker: true
    )

    private static let draft = DemoFeature(
        "draft", "待确认草稿", "核对教练给出的记录建议",
        tab: .coach, icon: "doc.text",
        rows: [("示例草稿", "为午餐添加鸡胸肉"), ("估算份量", "150 克"), ("确认前", "可以调整份量或取消")]
    )

    private static let coachReminders = DemoFeature(
        "coachReminders", "温馨提醒", "查看教练的主动提醒设置",
        tab: .coach, icon: "bell",
        rows: [("提醒范围", "训练与恢复、饮食记录"), ("提醒时间", "时间段和免打扰"), ("提醒控制", "暂停一天或恢复")]
    )

    private static let profile = DemoFeature(
        "profile", "个人资料", "查看账号与基本信息",
        tab: .account,
        rows: [("账号", "示例账号"), ("昵称", "NxtRep 用户")]
    )

    private static let preferences = DemoFeature(
        "preferences", "训练偏好", "管理目标、器械和每周安排",
        tab: .account, icon: "dumbbell",
        rows: [("训练目标", "力量提升"), ("可用器械", "杠铃、哑铃"), ("每周计划", "3 次")]
    )

    private static let privacy = DemoFeature(
        "privacy", "应用与隐私", "查看应用设置与数据选项",
        tab: .account, icon: "hand.raised",
        rows: [("计量单位", "身体数据与训练重量"), ("首页提醒隐私", "控制提醒内容的展示")]
    )

    private static let security = DemoFeature(
        "security", "账户安全", "修改密码和管理登录设备",
        tab: .account, icon: "lock.shield",
        rows: [("密码", "修改登录密码"), ("设备管理", "查看已登录设备")]
    )

    private static let offline = DemoFeature(
        "offline", "离线记录与草稿", "查看待同步记录并恢复草稿",
        tab: .account, icon: "tray",
        rows: [("待同步记录", "0 条"), ("本机草稿", "训练与饮食")]
    )

    private static let reminders = DemoFeature(
        "reminders", "手机系统提醒", "定时提醒、权限与免打扰",
        tab: .account, icon: "bell",
        rows: [("提醒类型", "训练、三餐、饮水、身体记录"), ("时间安排", "星期、时段与免打扰"), ("通知权限", "由手机系统管理")]
    )
}
