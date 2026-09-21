import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../domain/profile_models.dart';
import 'profile_controller.dart';

class ProfilePage extends StatefulWidget {
  const ProfilePage({
    super.key,
    required this.controller,
    required this.username,
    required this.loggingOut,
    required this.onLogout,
  });

  final ProfileController controller;
  final String username;
  final bool loggingOut;
  final Future<void> Function() onLogout;

  @override
  State<ProfilePage> createState() => _ProfilePageState();
}

class _ProfilePageState extends State<ProfilePage> {
  @override
  void initState() {
    super.initState();
    if (!widget.controller.ready) {
      widget.controller.refresh();
    }
  }

  Future<void> _open(Widget page, String successMessage) async {
    final saved = await Navigator.of(context)
        .push<bool>(MaterialPageRoute<bool>(builder: (_) => page));
    if (saved == true && mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(successMessage)));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: ListenableBuilder(
          listenable: widget.controller,
          builder: (context, _) {
            final profile = widget.controller.profile;
            final preferences = widget.controller.trainingPreferences;
            final settings = widget.controller.settings;
            final displayName = profile?.displayName?.trim();
            return RefreshIndicator(
              onRefresh: widget.controller.refresh,
              child: ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.fromLTRB(20, 24, 20, 32),
                children: [
                  const AppPageHeader(title: '我的', subtitle: '资料、训练偏好与隐私设置'),
                  const SizedBox(height: 24),
                  AppSurface(
                    color: AppColors.darkCard,
                    borderColor: AppColors.darkCard,
                    padding: const EdgeInsets.all(20),
                    child: Row(
                      children: [
                        Container(
                          width: 58,
                          height: 58,
                          decoration: BoxDecoration(
                            color: Colors.white.withValues(alpha: 0.12),
                            borderRadius: BorderRadius.circular(19),
                          ),
                          child: const Icon(
                            Icons.person_rounded,
                            color: Colors.white,
                            size: 30,
                          ),
                        ),
                        const SizedBox(width: 15),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                displayName?.isNotEmpty == true
                                    ? displayName!
                                    : widget.username,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: Theme.of(context).textTheme.titleLarge
                                    ?.copyWith(color: Colors.white),
                              ),
                              const SizedBox(height: 5),
                              Text(
                                profile == null
                                    ? '正在同步资料…'
                                    : _profileSummary(profile),
                                style: Theme.of(context).textTheme.bodyMedium
                                    ?.copyWith(color: Colors.white70),
                              ),
                            ],
                          ),
                        ),
                        StatusPill(
                          label: widget.controller.loading ? '同步中' : '已连接',
                          color: const Color(0xFF68D4B9),
                          icon: widget.controller.loading
                              ? Icons.sync_rounded
                              : Icons.cloud_done_outlined,
                        ),
                      ],
                    ),
                  ),
                  if (widget.controller.errorMessage case final message?) ...[
                    const SizedBox(height: 14),
                    AppErrorCard(message: message),
                  ],
                  const SizedBox(height: 28),
                  const SectionTitle(title: '账户与偏好'),
                  const SizedBox(height: 12),
                  AppSurface(
                    padding: EdgeInsets.zero,
                    child: Column(
                      children: [
                        _ProfileAction(
                          icon: Icons.person_outline_rounded,
                          title: '个人资料',
                          subtitle: profile == null
                              ? '正在加载'
                              : _personalSummary(profile),
                          enabled: profile != null,
                          onTap: () => _open(
                            PersonalProfilePage(controller: widget.controller),
                            '个人资料已保存',
                          ),
                        ),
                        const Divider(height: 1, indent: 70),
                        _ProfileAction(
                          icon: Icons.fitness_center_rounded,
                          title: '训练偏好',
                          subtitle: profile == null || preferences == null
                              ? '正在加载'
                              : _trainingSummary(profile, preferences),
                          enabled: profile != null && preferences != null,
                          onTap: () => _open(
                            TrainingPreferencesPage(
                              controller: widget.controller,
                            ),
                            '训练偏好已保存',
                          ),
                        ),
                        const Divider(height: 1, indent: 70),
                        _ProfileAction(
                          icon: Icons.verified_user_outlined,
                          title: '应用与隐私',
                          subtitle: settings == null
                              ? '正在加载'
                              : _settingsSummary(settings),
                          enabled: settings != null,
                          onTap: () => _open(
                            AppSettingsPage(controller: widget.controller),
                            '应用设置已保存',
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 20),
                  OutlinedButton.icon(
                    onPressed: widget.loggingOut ? null : widget.onLogout,
                    icon: const Icon(Icons.logout_rounded),
                    label: const Text('退出登录'),
                  ),
                ],
              ),
            );
          },
        ),
      ),
    );
  }
}

class PersonalProfilePage extends StatefulWidget {
  const PersonalProfilePage({super.key, required this.controller});

  final ProfileController controller;

  @override
  State<PersonalProfilePage> createState() => _PersonalProfilePageState();
}

class _PersonalProfilePageState extends State<PersonalProfilePage> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _displayName;
  late final TextEditingController _height;
  late final TextEditingController _sessionMinutes;
  late String _sex;
  late String? _experienceLevel;
  late DateTime? _birthDate;

  UserProfile get _profile => widget.controller.profile!;

  @override
  void initState() {
    super.initState();
    final profile = _profile;
    _displayName = TextEditingController(text: profile.displayName ?? '');
    _height = TextEditingController(
      text: profile.heightCm?.toStringAsFixed(1) ?? '',
    );
    _sessionMinutes = TextEditingController(
      text: profile.sessionDurationMinutes?.toString() ?? '',
    );
    _sex = profile.sex;
    _experienceLevel = profile.experienceLevel;
    _birthDate = profile.birthDate;
  }

  @override
  void dispose() {
    _displayName.dispose();
    _height.dispose();
    _sessionMinutes.dispose();
    super.dispose();
  }

  Future<void> _pickBirthDate() async {
    final selected = await showDatePicker(
      context: context,
      initialDate: _birthDate ?? DateTime(2000, 1, 1),
      firstDate: DateTime(1900, 1, 1),
      lastDate: DateTime.now(),
    );
    if (selected != null) setState(() => _birthDate = selected);
  }

  Future<void> _save() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    final saved = await widget.controller.savePersonal(
      PersonalProfileInput(
        displayName: _nullable(_displayName.text),
        sex: _sex,
        birthDate: _birthDate,
        heightCm: double.tryParse(_height.text.trim()),
        experienceLevel: _experienceLevel,
        sessionDurationMinutes: int.tryParse(_sessionMinutes.text.trim()),
      ),
    );
    if (saved && mounted) Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('个人资料')),
      body: ListenableBuilder(
        listenable: widget.controller,
        builder: (context, _) => Form(
          key: _formKey,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(20, 8, 20, 32),
            children: [
              const _FormIntro(
                icon: Icons.person_outline_rounded,
                title: '完善基础资料',
                message: '这些信息用于生成更合适的训练建议，不会公开展示。',
              ),
              const SizedBox(height: 20),
              TextFormField(
                controller: _displayName,
                maxLength: 80,
                decoration: const InputDecoration(labelText: '昵称（可选）'),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                initialValue: _sex,
                decoration: const InputDecoration(labelText: '性别'),
                items: const [
                  DropdownMenuItem(value: 'unspecified', child: Text('暂不填写')),
                  DropdownMenuItem(value: 'male', child: Text('男')),
                  DropdownMenuItem(value: 'female', child: Text('女')),
                  DropdownMenuItem(value: 'other', child: Text('其他')),
                ],
                onChanged: (value) => _sex = value!,
              ),
              const SizedBox(height: 12),
              _DateField(
                value: _birthDate,
                onTap: _pickBirthDate,
                onClear: () => setState(() => _birthDate = null),
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _height,
                keyboardType: const TextInputType.numberWithOptions(
                  decimal: true,
                ),
                inputFormatters: [
                  FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
                ],
                decoration: const InputDecoration(labelText: '身高（cm）'),
                validator: (value) => _optionalNumberError(
                  value,
                  min: 1,
                  max: 300,
                  message: '请输入 1–300 cm',
                ),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<String?>(
                initialValue: _experienceLevel,
                decoration: const InputDecoration(labelText: '训练经验'),
                items: const [
                  DropdownMenuItem(value: null, child: Text('暂不填写')),
                  DropdownMenuItem(value: 'beginner', child: Text('新手')),
                  DropdownMenuItem(value: 'intermediate', child: Text('有一定经验')),
                  DropdownMenuItem(value: 'advanced', child: Text('进阶训练者')),
                ],
                onChanged: (value) => _experienceLevel = value,
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _sessionMinutes,
                keyboardType: TextInputType.number,
                inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                decoration: const InputDecoration(labelText: '单次训练时长（分钟）'),
                validator: (value) => _optionalNumberError(
                  value,
                  min: 1,
                  max: 1440,
                  message: '请输入 1–1440 分钟',
                ),
              ),
              if (widget.controller.errorMessage case final message?) ...[
                const SizedBox(height: 14),
                AppErrorCard(message: message),
              ],
              const SizedBox(height: 22),
              FilledButton(
                onPressed: widget.controller.saving ? null : _save,
                child: _SavingLabel(
                  saving: widget.controller.saving,
                  label: '保存个人资料',
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class TrainingPreferencesPage extends StatefulWidget {
  const TrainingPreferencesPage({super.key, required this.controller});

  final ProfileController controller;

  @override
  State<TrainingPreferencesPage> createState() =>
      _TrainingPreferencesPageState();
}

class _TrainingPreferencesPageState extends State<TrainingPreferencesPage> {
  static const _goals = <String, String>{
    'muscle_gain': '增肌',
    'fat_loss_retain': '减脂保肌',
    'recomposition': '增肌减脂',
    'maintain': '保持状态',
    'strength': '提升力量',
  };

  late String _goalType;
  late int _weeklyDays;
  late ProfileTrainingMode _trainingMode;

  @override
  void initState() {
    super.initState();
    final profile = widget.controller.profile!;
    final preferences = widget.controller.trainingPreferences!;
    _goalType = preferences.goalType;
    _weeklyDays = profile.weeklyTrainingDays ?? 3;
    _trainingMode = preferences.trainingMode;
  }

  Future<void> _save() async {
    final saved = await widget.controller.saveTraining(
      TrainingPreferencesInput(
        goalType: _goalType,
        weeklyTrainingDays: _weeklyDays,
        trainingMode: _trainingMode,
      ),
    );
    if (saved && mounted) Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) {
    final injuries = widget.controller.trainingPreferences!.painOrInjuries;
    return Scaffold(
      appBar: AppBar(title: const Text('训练偏好')),
      body: ListenableBuilder(
        listenable: widget.controller,
        builder: (context, _) => ListView(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 32),
          children: [
            const _FormIntro(
              icon: Icons.fitness_center_rounded,
              title: '调整训练方向',
              message: '频率和训练环境会影响计划安排，尽量按现实条件选择。',
            ),
            const SizedBox(height: 24),
            Text('当前目标', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 10),
            Wrap(
              spacing: 9,
              runSpacing: 9,
              children: _goals.entries
                  .map(
                    (item) => ChoiceChip(
                      label: Text(item.value),
                      selected: _goalType == item.key,
                      onSelected: (_) => setState(() => _goalType = item.key),
                    ),
                  )
                  .toList(growable: false),
            ),
            const SizedBox(height: 24),
            Text('每周训练次数', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 10),
            Wrap(
              spacing: 9,
              runSpacing: 9,
              children: [
                for (var days = 1; days <= 7; days++)
                  ChoiceChip(
                    label: Text('$days 次'),
                    selected: _weeklyDays == days,
                    onSelected: (_) => setState(() => _weeklyDays = days),
                  ),
              ],
            ),
            const SizedBox(height: 24),
            Text('常用训练方式', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 10),
            _TrainingModeCard(
              selected: _trainingMode == ProfileTrainingMode.bodyweight,
              icon: Icons.accessibility_new_rounded,
              title: '徒手训练',
              subtitle: '不依赖健身器械，适合家中或户外训练',
              onTap: () => setState(
                () => _trainingMode = ProfileTrainingMode.bodyweight,
              ),
            ),
            const SizedBox(height: 10),
            _TrainingModeCard(
              selected: _trainingMode == ProfileTrainingMode.gymEquipment,
              icon: Icons.fitness_center_rounded,
              title: '健身房器械训练',
              subtitle: '使用哑铃、杠铃、绳索和深蹲架等器械',
              onTap: () => setState(
                () => _trainingMode = ProfileTrainingMode.gymEquipment,
              ),
            ),
            if (injuries.isNotEmpty) ...[
              const SizedBox(height: 20),
              AppSurface(
                color: AppColors.amberSoft,
                borderColor: AppColors.amber.withValues(alpha: 0.2),
                padding: const EdgeInsets.all(14),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(
                      Icons.health_and_safety_outlined,
                      color: AppColors.amber,
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        '已保留动作限制：${injuries.map((item) => item.bodyPart).join('、')}',
                      ),
                    ),
                  ],
                ),
              ),
            ],
            if (widget.controller.errorMessage case final message?) ...[
              const SizedBox(height: 14),
              AppErrorCard(message: message),
            ],
            const SizedBox(height: 22),
            FilledButton(
              onPressed: widget.controller.saving ? null : _save,
              child: _SavingLabel(
                saving: widget.controller.saving,
                label: '保存训练偏好',
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class AppSettingsPage extends StatefulWidget {
  const AppSettingsPage({super.key, required this.controller});

  final ProfileController controller;

  @override
  State<AppSettingsPage> createState() => _AppSettingsPageState();
}

class _AppSettingsPageState extends State<AppSettingsPage> {
  late String _unitSystem;
  late String _privacyMode;
  late bool _shareAnalytics;

  @override
  void initState() {
    super.initState();
    final settings = widget.controller.settings!;
    _unitSystem = settings.unitSystem;
    _privacyMode = settings.privacyMode;
    _shareAnalytics = settings.shareAnonymousAnalytics;
  }

  Future<void> _save() async {
    final saved = await widget.controller.saveSettings(
      AppSettingsInput(
        unitSystem: _unitSystem,
        privacyMode: _privacyMode,
        shareAnonymousAnalytics: _shareAnalytics,
      ),
    );
    if (saved && mounted) Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) {
    final timezone = widget.controller.settings!.timezone;
    return Scaffold(
      appBar: AppBar(title: const Text('应用与隐私')),
      body: ListenableBuilder(
        listenable: widget.controller,
        builder: (context, _) => ListView(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 32),
          children: [
            const _FormIntro(
              icon: Icons.verified_user_outlined,
              title: '由你控制的数据设置',
              message: '训练记录默认仅自己可见；匿名分析开关不会影响核心功能。',
            ),
            const SizedBox(height: 24),
            Text('计量单位', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 10),
            SegmentedButton<String>(
              segments: const [
                ButtonSegment(value: 'metric', label: Text('公制 kg / cm')),
                ButtonSegment(value: 'imperial', label: Text('英制 lb / in')),
              ],
              selected: {_unitSystem},
              onSelectionChanged: (value) {
                setState(() => _unitSystem = value.single);
              },
            ),
            const SizedBox(height: 24),
            Text('隐私模式', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 10),
            SegmentedButton<String>(
              segments: const [
                ButtonSegment(value: 'private', label: Text('完全私密')),
                ButtonSegment(value: 'summary', label: Text('仅汇总信息')),
              ],
              selected: {_privacyMode},
              onSelectionChanged: (value) {
                setState(() => _privacyMode = value.single);
              },
            ),
            const SizedBox(height: 18),
            AppSurface(
              padding: EdgeInsets.zero,
              child: SwitchListTile.adaptive(
                contentPadding: const EdgeInsets.symmetric(horizontal: 16),
                title: const Text('分享匿名使用数据'),
                subtitle: const Text('帮助改进稳定性，不包含训练照片和对话正文'),
                value: _shareAnalytics,
                onChanged: (value) => setState(() => _shareAnalytics = value),
              ),
            ),
            const SizedBox(height: 12),
            AppSurface(
              padding: const EdgeInsets.all(16),
              child: Row(
                children: [
                  const Icon(Icons.schedule_rounded, color: AppColors.indigo),
                  const SizedBox(width: 12),
                  Expanded(child: Text('当前时区：$timezone')),
                ],
              ),
            ),
            if (widget.controller.errorMessage case final message?) ...[
              const SizedBox(height: 14),
              AppErrorCard(message: message),
            ],
            const SizedBox(height: 22),
            FilledButton(
              onPressed: widget.controller.saving ? null : _save,
              child: _SavingLabel(
                saving: widget.controller.saving,
                label: '保存应用设置',
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ProfileAction extends StatelessWidget {
  const _ProfileAction({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.enabled,
    required this.onTap,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final bool enabled;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      onTap: enabled ? onTap : null,
      minTileHeight: 76,
      leading: Container(
        width: 42,
        height: 42,
        decoration: BoxDecoration(
          color: AppColors.indigoSoft,
          borderRadius: BorderRadius.circular(14),
        ),
        child: Icon(icon, color: AppColors.indigo, size: 22),
      ),
      title: Text(title, style: Theme.of(context).textTheme.titleMedium),
      subtitle: Text(subtitle, maxLines: 1, overflow: TextOverflow.ellipsis),
      trailing: const Icon(Icons.chevron_right_rounded, color: AppColors.muted),
    );
  }
}

class _TrainingModeCard extends StatelessWidget {
  const _TrainingModeCard({
    required this.selected,
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  final bool selected;
  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return AppSurface(
      onTap: onTap,
      color: selected ? AppColors.primarySoft : AppColors.surface,
      borderColor: selected ? AppColors.primary : AppColors.line,
      padding: const EdgeInsets.all(16),
      child: Row(
        children: [
          Container(
            width: 46,
            height: 46,
            decoration: BoxDecoration(
              color: selected
                  ? AppColors.primary.withValues(alpha: 0.12)
                  : AppColors.indigoSoft,
              borderRadius: BorderRadius.circular(15),
            ),
            child: Icon(
              icon,
              color: selected ? AppColors.primary : AppColors.indigo,
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 4),
                Text(
                  subtitle,
                  style: Theme.of(context).textTheme.bodyMedium
                      ?.copyWith(color: AppColors.muted),
                ),
              ],
            ),
          ),
          Icon(
            selected ? Icons.check_circle_rounded : Icons.circle_outlined,
            color: selected ? AppColors.primary : AppColors.muted,
          ),
        ],
      ),
    );
  }
}

class _FormIntro extends StatelessWidget {
  const _FormIntro({
    required this.icon,
    required this.title,
    required this.message,
  });

  final IconData icon;
  final String title;
  final String message;

  @override
  Widget build(BuildContext context) {
    return AppSurface(
      color: AppColors.indigoSoft,
      borderColor: AppColors.indigo.withValues(alpha: 0.12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: AppColors.indigo),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 4),
                Text(message),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _DateField extends StatelessWidget {
  const _DateField({
    required this.value,
    required this.onTap,
    required this.onClear,
  });

  final DateTime? value;
  final VoidCallback onTap;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    return AppSurface(
      onTap: onTap,
      color: const Color(0xFFF1F2F6),
      borderColor: Colors.transparent,
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('出生日期', style: Theme.of(context).textTheme.labelMedium),
                const SizedBox(height: 4),
                Text(value == null ? '暂不填写' : _formatDate(value!)),
              ],
            ),
          ),
          if (value != null)
            IconButton(
              tooltip: '清除',
              onPressed: onClear,
              icon: const Icon(Icons.close_rounded),
            )
          else
            const Icon(Icons.calendar_today_outlined, color: AppColors.muted),
        ],
      ),
    );
  }
}

class _SavingLabel extends StatelessWidget {
  const _SavingLabel({required this.saving, required this.label});

  final bool saving;
  final String label;

  @override
  Widget build(BuildContext context) {
    if (!saving) return Text(label);
    return const SizedBox.square(
      dimension: 20,
      child: CircularProgressIndicator(strokeWidth: 2),
    );
  }
}

String _profileSummary(UserProfile profile) {
  final level = switch (profile.experienceLevel) {
    'intermediate' => '有一定经验',
    'advanced' => '进阶训练者',
    _ => '新手训练者',
  };
  return '${profile.weeklyTrainingDays ?? 0} 次/周 · $level';
}

String _personalSummary(UserProfile profile) {
  final height = profile.heightCm == null
      ? '身高待补充'
      : '${profile.heightCm!.toStringAsFixed(0)} cm';
  return '${profile.displayName ?? '昵称待补充'} · $height';
}

String _trainingSummary(UserProfile profile, TrainingPreferences preferences) {
  final mode = preferences.trainingMode == ProfileTrainingMode.bodyweight
      ? '徒手训练'
      : '健身房器械';
  return '${_goalLabel(preferences.goalType)} · ${profile.weeklyTrainingDays ?? 0} 次/周 · $mode';
}

String _settingsSummary(AppSettings settings) {
  final units = settings.unitSystem == 'metric' ? '公制' : '英制';
  final privacy = settings.privacyMode == 'private' ? '完全私密' : '仅汇总信息';
  return '$units · $privacy';
}

String _goalLabel(String value) => switch (value) {
  'muscle_gain' => '增肌',
  'fat_loss_retain' => '减脂保肌',
  'recomposition' => '增肌减脂',
  'maintain' => '保持状态',
  'strength' => '提升力量',
  _ => '训练目标',
};

String? _nullable(String value) {
  final normalized = value.trim();
  return normalized.isEmpty ? null : normalized;
}

String? _optionalNumberError(
  String? value, {
  required num min,
  required num max,
  required String message,
}) {
  if (value == null || value.trim().isEmpty) return null;
  final number = num.tryParse(value.trim());
  return number == null || number < min || number > max ? message : null;
}

String _formatDate(DateTime value) {
  final month = value.month.toString().padLeft(2, '0');
  final day = value.day.toString().padLeft(2, '0');
  return '${value.year}-$month-$day';
}
