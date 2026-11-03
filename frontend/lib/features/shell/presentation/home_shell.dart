import 'dart:async';

import 'package:flutter/material.dart';

import '../../../core/offline/local_records_page.dart';
import '../../../core/notifications/reminder_models.dart';
import '../../profile/presentation/local_reminders_page.dart';

import '../../../core/media/image_upload.dart';
import '../../../core/theme/app_theme.dart';
import '../../agent/data/agent_repository.dart';
import '../../agent/data/proactive_repository.dart';
import '../../agent/presentation/agent_controller.dart';
import '../../agent/presentation/agent_page.dart';
import '../../agent/presentation/proactive_controller.dart';
import '../../auth/presentation/session_controller.dart';
import '../../auth/presentation/account_security_controller.dart';
import '../../auth/presentation/account_security_page.dart';
import '../../exercises/data/exercise_repository.dart';
import '../../exercises/presentation/exercise_library_page.dart';
import '../../nutrition/data/nutrition_repository.dart';
import '../../nutrition/presentation/nutrition_controller.dart';
import '../../nutrition/presentation/nutrition_page.dart';
import '../../nutrition/presentation/nutrition_photo_page.dart';
import '../../nutrition/presentation/water_entry_sheet.dart';
import '../../progress/data/body_repository.dart';
import '../../progress/data/body_progress_repository.dart';
import '../../progress/presentation/body_progress_controller.dart';
import '../../progress/presentation/body_progress_page.dart';
import '../../progress/presentation/progress_controller.dart';
import '../../progress/presentation/progress_page.dart';
import '../../profile/data/profile_repository.dart';
import '../../profile/presentation/profile_controller.dart';
import '../../profile/presentation/profile_page.dart';
import '../../training/data/training_repository.dart';
import '../../training/presentation/plan_controller.dart';
import '../../training/presentation/plan_page.dart';
import '../../training/presentation/today_page.dart';
import '../../training/presentation/training_controller.dart';

class HomeShell extends StatefulWidget {
  const HomeShell({super.key, required this.controller});

  final SessionController controller;

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> with WidgetsBindingObserver {
  int _index = 0;
  DateTime _selectedDate = DateUtils.dateOnly(DateTime.now());
  late final TrainingController _trainingController;
  late final ImageUploadRepository _imageUploadRepository;
  late final AgentController _agentController;
  late final ProactiveController _proactiveController;
  late final NutritionController _nutritionController;
  late final ProgressController _progressController;
  late final BodyProgressController _bodyProgressController;
  late final PlanController _planController;
  late final ProfileController _profileController;
  late final ExerciseRepository _exerciseRepository;
  Timer? _syncTimer;
  bool _reminderNavigationQueued = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    widget.controller.systemReminders?.addListener(_onReminderChanged);
    WidgetsBinding.instance.addPostFrameCallback((_) => _onReminderChanged());
    _syncTimer = Timer.periodic(const Duration(seconds: 30), (_) => _sync());
    WidgetsBinding.instance.addPostFrameCallback((_) => _sync());
    _trainingController = TrainingController(
      TrainingRepository(widget.controller.authRepository.apiClient),
    );
    _imageUploadRepository = ImageUploadRepository(
      widget.controller.authRepository.apiClient,
    );
    _agentController = AgentController(
      AgentRepository(widget.controller.authRepository.apiClient),
      imageUploader: _imageUploadRepository.uploadChatImage,
    );
    _proactiveController = ProactiveController(
      ProactiveRepository(widget.controller.authRepository.apiClient),
    );
    _nutritionController = NutritionController(
      NutritionRepository(widget.controller.authRepository.apiClient),
      imageUploader: _imageUploadRepository.uploadNutritionImage,
    );
    _progressController = ProgressController(
      BodyRepository(widget.controller.authRepository.apiClient),
    );
    _bodyProgressController = BodyProgressController(
      BodyProgressRepository(widget.controller.authRepository.apiClient),
      _imageUploadRepository.uploadBodyProgressImage,
    );
    _planController = PlanController(
      TrainingRepository(widget.controller.authRepository.apiClient),
      imageUploader: _imageUploadRepository.uploadTrainingPlanImage,
      profileRepository: ProfileRepository(
        widget.controller.authRepository.apiClient,
      ),
    );
    _profileController = ProfileController(
      ProfileRepository(widget.controller.authRepository.apiClient),
      onSettingsChanged: (settings) {
        if (mounted) widget.controller.applySettings(settings);
      },
    );
    _exerciseRepository = ExerciseRepository(
      widget.controller.authRepository.apiClient,
    );
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    widget.controller.systemReminders?.removeListener(_onReminderChanged);
    _syncTimer?.cancel();
    _trainingController.dispose();
    _agentController.dispose();
    _proactiveController.dispose();
    _imageUploadRepository.close();
    _nutritionController.dispose();
    _progressController.dispose();
    _bodyProgressController.dispose();
    _planController.dispose();
    _profileController.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _sync();
  }

  Future<void> _sync() async {
    if (!mounted ||
        WidgetsBinding.instance.lifecycleState == AppLifecycleState.paused) {
      return;
    }
    final before = widget.controller.localRecords?.syncRevision;
    await widget.controller.reconnectAndSync();
    if (!mounted || before == widget.controller.localRecords?.syncRevision) {
      return;
    }
    await Future.wait([
      _trainingController.refresh(),
      _nutritionController.refresh(),
      _progressController.refresh(),
    ]);
  }

  void _openLocalRecords() {
    final records = widget.controller.localRecords;
    if (records == null) return;
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => LocalRecordsPage(
          records: records,
          onSync: _sync,
          onOpenDraft: _resumeDraft,
        ),
      ),
    );
  }

  Future<void> _resumeDraft(String key) async {
    Navigator.of(context).pop();
    if (key == 'agent-input') {
      _selectTab(4);
      return;
    }
    if (key.startsWith('photo:')) {
      final date = DateTime.tryParse(key.substring(6));
      if (date != null) {
        _selectDate(date);
        _selectTab(2);
        await Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) => NutritionPhotoPage(
              controller: _nutritionController,
              recordDate: date,
            ),
          ),
        );
      }
      return;
    }
    final meal = RegExp(r'^meal:(.+):(breakfast|lunch|dinner|snack|other)$')
        .firstMatch(key);
    if (meal != null) {
      final date = DateTime.parse(meal.group(1)!);
      _selectDate(date);
      _selectTab(2);
      await showManualNutritionEntry(
        context,
        _nutritionController,
        date,
        meal.group(2)!,
      );
      return;
    }
    if (key.startsWith('water:')) {
      final date = DateTime.parse(key.substring(6));
      _selectDate(date);
      _selectTab(2);
      await showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        builder: (_) => WaterEntrySheet(controller: _nutritionController),
      );
      return;
    }
    if (key.startsWith('measurement:')) {
      _selectTab(3);
      if (key == 'measurement:new') {
        await showBodyMeasurementEntry(context, _progressController);
      } else {
        final measurements = _progressController.measurements.where(
          (e) => key == 'measurement:${e.id}',
        );
        if (measurements.isNotEmpty) {
          await showBodyMeasurementEntry(
            context,
            _progressController,
            measurement: measurements.first,
          );
        }
      }
      return;
    }
    if (key.startsWith('set:')) {
      _selectTab(0);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('打开进行中的训练，再选择对应动作，即可恢复训练组输入')),
      );
    }
  }

  void _openSystemReminders() {
    final reminders = widget.controller.systemReminders;
    if (reminders == null) return;
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => LocalRemindersPage(controller: reminders),
      ),
    );
  }

  void _onReminderChanged() {
    if (!mounted ||
        _reminderNavigationQueued ||
        widget.controller.systemReminders?.hasNavigation != true) {
      return;
    }
    _reminderNavigationQueued = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _reminderNavigationQueued = false;
      if (!mounted || widget.controller.phase != SessionPhase.authenticated) {
        return;
      }
      final kind = widget.controller.systemReminders?.takeNavigation();
      if (kind == null) return;
      Navigator.of(context).popUntil((route) => route.isFirst);
      if (kind == ReminderKind.training) {
        _selectTab(0);
        return;
      }
      if (kind == ReminderKind.measurement) {
        _selectTab(3);
        showBodyMeasurementEntry(context, _progressController);
        return;
      }
      _selectDate(DateUtils.dateOnly(DateTime.now()));
      _selectTab(2);
      if (kind == ReminderKind.water) {
        showModalBottomSheet<void>(
          context: context,
          isScrollControlled: true,
          builder: (_) => WaterEntrySheet(controller: _nutritionController),
        );
      }
    });
  }

  void _selectTab(int value) {
    if (value == 0) {
      _trainingController.refresh();
      _proactiveController.refresh();
    }
    if (value == 1) _planController.refresh();
    if (value == 2) _nutritionController.refresh();
    if (value == 3) _progressController.refresh();
    if (value == 5) _profileController.refresh();
    setState(() => _index = value);
  }

  void _selectDate(DateTime date) {
    setState(() => _selectedDate = DateUtils.dateOnly(date));
    _nutritionController.selectDate(_selectedDate);
  }

  void _openExerciseLibrary() => Navigator.of(context).push(
    MaterialPageRoute<void>(
      builder: (_) => ExerciseLibraryPage(repository: _exerciseRepository),
    ),
  );

  Future<void> _openAccountSecurity() async {
    final security = AccountSecurityController(
      widget.controller.authRepository,
      onRequireLogin: widget.controller.requireLogin,
    );
    try {
      await Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => AccountSecurityPage(controller: security),
        ),
      );
    } finally {
      security.dispose();
    }
  }

  @override
  Widget build(BuildContext context) {
    final pages = <Widget>[
      TodayPage(
        username: widget.controller.account?.username ?? '',
        controller: _trainingController,
        proactiveController: _proactiveController,
        exerciseRepository: _exerciseRepository,
        onOpenPlan: () => _selectTab(1),
        onOpenProgress: () => _selectTab(3),
        onOpenAgent: () => _selectTab(4),
        onOpenExerciseLibrary: _openExerciseLibrary,
        onDiscussNotice: (notice) async {
          final prompt = switch (notice.kind) {
            'missed_workout' =>
              '昨天日历中的训练尚未标记完成。请先核对我的训练记录和日历，若需要调整，只提出草稿供我确认，不要直接修改。',
            'recovery_check' =>
              '昨天我记录了较高训练后疲劳。请先核对记录与今天安排，讨论安全的调整；如需变更，先提出草稿等我确认。',
            'nutrition_log_gap' =>
              '昨天没有饮食记录，请帮我核对，但不要假设我没有进食。如需补记或调整，请先提出草稿供我确认。',
            _ => '请根据这条主动建议先核对事实，再讨论是否需要调整；任何变更都请先提出草稿等我确认。',
          };
          _selectTab(4);
          await _agentController.send(prompt);
        },
        onOpenNutrition: () => _selectTab(2),
      ),
      PlanPage(
        controller: _planController,
        selectedDate: _selectedDate,
        onDateSelected: _selectDate,
        onOpenNutrition: () => _selectTab(2),
        onOpenExerciseLibrary: _openExerciseLibrary,
        onAskCoach: (prompt) async {
          _selectTab(4);
          await _agentController.send(prompt);
        },
      ),
      NutritionPage(
        controller: _nutritionController,
        embedded: true,
        onDateSelected: _selectDate,
        onOpenPlan: () => _selectTab(1),
      ),
      ProgressPage(
        controller: _progressController,
        onOpenBodyProgress: () => Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) =>
                BodyProgressPage(controller: _bodyProgressController),
          ),
        ),
      ),
      AgentPage(controller: _agentController),
      ProfilePage(
        controller: _profileController,
        username: widget.controller.account?.username ?? '',
        loggingOut: widget.controller.submitting,
        onLogout: widget.controller.logout,
        onOpenSecurity: _openAccountSecurity,
        onOpenSystemReminders: widget.controller.systemReminders == null
            ? null
            : _openSystemReminders,
        onOpenLocalRecords: widget.controller.localRecords == null
            ? null
            : _openLocalRecords,
      ),
    ];

    return Scaffold(
      body: Column(
        children: [
          if (widget.controller.localRecords case final records?)
            ListenableBuilder(
              listenable: records,
              builder: (context, _) {
                if (!records.localOnly &&
                    !records.usingCache &&
                    records.pending.isEmpty &&
                    records.storageError == null) {
                  return const SizedBox.shrink();
                }
                return SafeArea(
                  bottom: false,
                  child: Material(
                    color: AppColors.amberSoft,
                    child: InkWell(
                      onTap: _openLocalRecords,
                      child: Padding(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 16,
                          vertical: 10,
                        ),
                        child: Row(
                          children: [
                            const Icon(Icons.cloud_off_outlined, size: 20),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(
                                records.storageError ??
                                    (records.needsAttention
                                        ? '${records.pending.length} 条待同步，部分需要核对 · 查看'
                                        : records.pending.isNotEmpty
                                        ? '已保存在本机 · ${records.pending.length} 条待同步 · 查看'
                                        : '正在查看本机缓存 · 联网后刷新'),
                              ),
                            ),
                            const Icon(Icons.chevron_right, size: 18),
                          ],
                        ),
                      ),
                    ),
                  ),
                );
              },
            ),
          Expanded(
            child: IndexedStack(index: _index, children: pages),
          ),
        ],
      ),
      bottomNavigationBar: DecoratedBox(
        decoration: const BoxDecoration(
          color: Colors.white,
          border: Border(top: BorderSide(color: AppColors.line, width: 0.8)),
        ),
        child: NavigationBar(
          selectedIndex: _index,
          onDestinationSelected: _selectTab,
          destinations: const [
            NavigationDestination(
              icon: Icon(Icons.home_outlined),
              selectedIcon: Icon(Icons.home_rounded),
              label: '首页',
            ),
            NavigationDestination(
              icon: Icon(Icons.bolt_outlined),
              selectedIcon: Icon(Icons.bolt_rounded),
              label: '计划',
            ),
            NavigationDestination(
              icon: Icon(Icons.restaurant_menu_outlined),
              selectedIcon: Icon(Icons.restaurant_menu_rounded),
              label: '饮食',
            ),
            NavigationDestination(
              icon: Icon(Icons.insights_outlined),
              selectedIcon: Icon(Icons.insights_rounded),
              label: '进展',
            ),
            NavigationDestination(
              icon: Icon(Icons.auto_awesome_outlined),
              selectedIcon: Icon(Icons.auto_awesome_rounded),
              label: 'AI私人教练',
            ),
            NavigationDestination(
              icon: Icon(Icons.person_outline_rounded),
              selectedIcon: Icon(Icons.person_rounded),
              label: '我的',
            ),
          ],
        ),
      ),
    );
  }
}
