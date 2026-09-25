import 'package:flutter/material.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../../agent/domain/proactive_models.dart';
import '../../agent/presentation/proactive_controller.dart';
import '../../exercises/data/exercise_repository.dart';
import '../domain/training_models.dart';
import 'training_controller.dart';
import 'workout_page.dart';

class TodayPage extends StatefulWidget {
  const TodayPage({
    super.key,
    required this.username,
    required this.controller,
    required this.proactiveController,
    required this.exerciseRepository,
    required this.onOpenNutrition,
    required this.onOpenPlan,
    required this.onOpenProgress,
    required this.onOpenAgent,
    required this.onDiscussNotice,
  });

  final String username;
  final TrainingController controller;
  final ProactiveController proactiveController;
  final ExerciseRepository exerciseRepository;
  final VoidCallback onOpenNutrition;
  final VoidCallback onOpenPlan;
  final VoidCallback onOpenProgress;
  final VoidCallback onOpenAgent;
  final ValueChanged<ProactiveNotice> onDiscussNotice;

  @override
  State<TodayPage> createState() => _TodayPageState();
}

class _PreWorkoutCheckSheet extends StatefulWidget {
  const _PreWorkoutCheckSheet({required this.defaultMinutes});

  final int defaultMinutes;

  @override
  State<_PreWorkoutCheckSheet> createState() => _PreWorkoutCheckSheetState();
}

class _PreWorkoutCheckSheetState extends State<_PreWorkoutCheckSheet> {
  int _sleep = 3;
  int _energy = 3;
  late int _minutes;

  @override
  void initState() {
    super.initState();
    _minutes = widget.defaultMinutes.clamp(15, 180);
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 22),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('训练前状态', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 6),
            const Text('告诉计划你今天的真实状态，后续调整会更准确。'),
            const SizedBox(height: 18),
            _CheckRating(
              label: '睡眠质量',
              value: _sleep,
              onChanged: (value) => setState(() => _sleep = value),
            ),
            const SizedBox(height: 14),
            _CheckRating(
              label: '当前精力',
              value: _energy,
              onChanged: (value) => setState(() => _energy = value),
            ),
            const SizedBox(height: 14),
            Text('可用时间：$_minutes 分钟'),
            Slider(
              value: _minutes.toDouble(),
              min: 15,
              max: 180,
              divisions: 11,
              label: '$_minutes 分钟',
              onChanged: (value) => setState(() => _minutes = value.round()),
            ),
            const SizedBox(height: 8),
            FilledButton(
              onPressed: () => Navigator.pop(
                context,
                PreWorkoutCheckInput(
                  sleepQuality: _sleep,
                  energy: _energy,
                  availableMinutes: _minutes,
                ),
              ),
              child: const Text('开始训练'),
            ),
          ],
        ),
      ),
    );
  }
}

class _CheckRating extends StatelessWidget {
  const _CheckRating({
    required this.label,
    required this.value,
    required this.onChanged,
  });

  final String label;
  final int value;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        SizedBox(width: 80, child: Text(label)),
        for (var rating = 1; rating <= 5; rating++) ...[
          Expanded(
            child: ChoiceChip(
              label: Text('$rating'),
              selected: value == rating,
              onSelected: (_) => onChanged(rating),
            ),
          ),
          if (rating < 5) const SizedBox(width: 5),
        ],
      ],
    );
  }
}

class _TodayPageState extends State<TodayPage> {
  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    await Future.wait<void>([
      widget.controller.refresh(),
      widget.proactiveController.refresh(),
    ]);
  }

  Future<void> _openNotice(ProactiveNotice notice) async {
    await widget.proactiveController.markRead(notice);
    if (!mounted) return;
    switch (notice.route) {
      case 'plan':
        widget.onOpenPlan();
      case 'nutrition':
        widget.onOpenNutrition();
      default:
        widget.onOpenAgent();
    }
  }

  Future<void> _openCoachInbox() async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => ListenableBuilder(
        listenable: widget.proactiveController,
        builder: (context, _) => SafeArea(
          child: SizedBox(
            height: MediaQuery.sizeOf(sheetContext).height * 0.65,
            child: ListView(
              padding: const EdgeInsets.fromLTRB(20, 20, 20, 28),
              children: [
                Text(
                  '主动教练建议',
                  style: Theme.of(sheetContext).textTheme.titleLarge,
                ),
                const SizedBox(height: 8),
                const Text('建议来自已记录的数据；点开后可查看或调整，教练不会自动改动计划。'),
                const SizedBox(height: 14),
                for (final notice in widget.proactiveController.notices)
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: Icon(_noticeIcon(notice.kind)),
                        title: Text(notice.title),
                        subtitle: Text(notice.body),
                        onTap: () {
                          Navigator.pop(sheetContext);
                          _openNotice(notice);
                        },
                      ),
                      _noticeActions(
                        notice,
                        closeSheet: () => Navigator.pop(sheetContext),
                      ),
                    ],
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  IconData _noticeIcon(String kind) => switch (kind) {
    'missed_workout' => Icons.event_repeat_rounded,
    'nutrition_log_gap' => Icons.restaurant_menu_rounded,
    'recovery_check' => Icons.self_improvement_rounded,
    _ => Icons.auto_awesome_rounded,
  };

  Widget _noticeActions(
    ProactiveNotice notice, {
    VoidCallback? closeSheet,
  }) => Wrap(
    spacing: 4,
    crossAxisAlignment: WrapCrossAlignment.center,
    children: [
      for (final (rating, label) in [
        ('helpful', '有帮助'),
        ('not_relevant', '不相关'),
        ('inaccurate', '内容不准'),
      ])
        TextButton(
          onPressed: notice.feedbackRating == rating
              ? null
              : () => widget.proactiveController.submitFeedback(notice, rating),
          child: Text(notice.feedbackRating == rating ? '已评价：$label' : label),
        ),
      TextButton.icon(
        onPressed: () {
          closeSheet?.call();
          widget.onDiscussNotice(notice);
        },
        icon: const Icon(Icons.chat_bubble_outline_rounded, size: 17),
        label: const Text('和教练讨论'),
      ),
    ],
  );

  Future<void> _openWorkout() async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => WorkoutPage(
          controller: widget.controller,
          exerciseRepository: widget.exerciseRepository,
        ),
      ),
    );
  }

  Future<void> _start(CalendarEvent event) async {
    final preCheck = await showModalBottomSheet<PreWorkoutCheckInput>(
      context: context,
      isScrollControlled: true,
      builder: (_) =>
          _PreWorkoutCheckSheet(defaultMinutes: event.estimatedMinutes),
    );
    if (preCheck == null) return;
    if (await widget.controller.start(event, preCheck: preCheck) && mounted) {
      await _openWorkout();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: ListenableBuilder(
          listenable: Listenable.merge([
            widget.controller,
            widget.proactiveController,
          ]),
          builder: (context, _) {
            final workout = widget.controller.activeWorkout;
            final nextEvent = widget.controller.events.isEmpty
                ? null
                : widget.controller.events.first;
            return RefreshIndicator(
              onRefresh: _refresh,
              child: ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.fromLTRB(20, 22, 20, 30),
                children: [
                  _HomeHeader(
                    username: widget.username,
                    refreshing:
                        widget.controller.loading ||
                        widget.proactiveController.loading,
                    onRefresh: _refresh,
                  ),
                  const SizedBox(height: 22),
                  if (widget.controller.errorMessage case final message?) ...[
                    AppErrorCard(message: message),
                    const SizedBox(height: 14),
                  ],
                  _TodayHero(
                    workout: workout,
                    event: nextEvent,
                    submitting: widget.controller.submitting,
                    onContinue: _openWorkout,
                    onStart: nextEvent == null ? null : () => _start(nextEvent),
                    onOpenPlan: widget.onOpenPlan,
                  ),
                  const SizedBox(height: 26),
                  const SectionTitle(title: '快速开始'),
                  const SizedBox(height: 12),
                  GridView.count(
                    crossAxisCount: 2,
                    shrinkWrap: true,
                    physics: const NeverScrollableScrollPhysics(),
                    mainAxisSpacing: 12,
                    crossAxisSpacing: 12,
                    childAspectRatio: 1.55,
                    children: [
                      QuickActionCard(
                        icon: Icons.bolt_rounded,
                        label: '训练计划',
                        subtitle: '查看本周安排',
                        tint: AppColors.primary,
                        onTap: widget.onOpenPlan,
                      ),
                      QuickActionCard(
                        icon: Icons.restaurant_menu_rounded,
                        label: '食品与饮食',
                        subtitle: '食品库、营养记录',
                        tint: AppColors.amber,
                        onTap: widget.onOpenNutrition,
                      ),
                      QuickActionCard(
                        icon: Icons.monitor_weight_outlined,
                        label: '身体数据',
                        subtitle: '查看变化趋势',
                        tint: AppColors.indigo,
                        onTap: widget.onOpenProgress,
                      ),
                      QuickActionCard(
                        icon: Icons.auto_awesome_rounded,
                        label: '问 AI 教练',
                        subtitle: '获得即时建议',
                        tint: AppColors.mint,
                        onTap: widget.onOpenAgent,
                      ),
                    ],
                  ),
                  const SizedBox(height: 26),
                  SectionTitle(
                    title: '主动教练',
                    action: widget.proactiveController.notices.length > 2
                        ? TextButton(
                            onPressed: _openCoachInbox,
                            child: const Text('查看全部'),
                          )
                        : null,
                  ),
                  const SizedBox(height: 10),
                  AppSurface(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            const Icon(
                              Icons.auto_awesome_rounded,
                              color: AppColors.mint,
                            ),
                            const SizedBox(width: 10),
                            const Expanded(child: Text('根据你的记录检查需要关注的事')),
                            Switch.adaptive(
                              value: widget.proactiveController.enabled,
                              onChanged:
                                  widget.proactiveController.settings == null ||
                                      widget.proactiveController.updating
                                  ? null
                                  : widget.proactiveController.setEnabled,
                            ),
                          ],
                        ),
                        const Text('开启后每日检查；只在应用内给建议，不会自动改动训练或饮食计划。'),
                        if (widget.proactiveController.errorMessage
                            case final message?) ...[
                          const SizedBox(height: 10),
                          AppErrorCard(message: message),
                        ],
                        if (widget.proactiveController.enabled) ...[
                          const Divider(height: 22),
                          if (widget.proactiveController.notices.isEmpty)
                            const Text('目前没有新的建议，继续按自己的节奏记录即可。'),
                          for (final notice
                              in widget.proactiveController.notices.take(2))
                            Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                ListTile(
                                  contentPadding: EdgeInsets.zero,
                                  leading: Icon(_noticeIcon(notice.kind)),
                                  title: Text(notice.title),
                                  subtitle: Text(notice.body),
                                  trailing: const Icon(
                                    Icons.chevron_right_rounded,
                                  ),
                                  onTap: () => _openNotice(notice),
                                ),
                                _noticeActions(notice),
                              ],
                            ),
                        ],
                      ],
                    ),
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

class _HomeHeader extends StatelessWidget {
  const _HomeHeader({
    required this.username,
    required this.refreshing,
    required this.onRefresh,
  });

  final String username;
  final bool refreshing;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    final now = DateTime.now();
    return Row(
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '你好，$username',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.headlineLarge,
              ),
              const SizedBox(height: 5),
              Text(
                '${now.month} 月 ${now.day} 日 · 今天也向目标靠近一点',
                style: Theme.of(context).textTheme.bodyMedium
                    ?.copyWith(color: AppColors.muted),
              ),
            ],
          ),
        ),
        const SizedBox(width: 12),
        IconButton.filledTonal(
          tooltip: '刷新',
          onPressed: refreshing ? null : onRefresh,
          icon: refreshing
              ? const SizedBox.square(
                  dimension: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.refresh_rounded),
        ),
      ],
    );
  }
}

class _TodayHero extends StatelessWidget {
  const _TodayHero({
    required this.workout,
    required this.event,
    required this.submitting,
    required this.onContinue,
    required this.onStart,
    required this.onOpenPlan,
  });

  final Workout? workout;
  final CalendarEvent? event;
  final bool submitting;
  final VoidCallback onContinue;
  final VoidCallback? onStart;
  final VoidCallback onOpenPlan;

  @override
  Widget build(BuildContext context) {
    final active = workout != null;
    final scheduled = !active && event != null;
    final completed = scheduled && event!.actualWorkoutId != null;
    final title = active
        ? '训练进行中'
        : scheduled
        ? event!.title
        : '今天是主动恢复日';
    final detail = active
        ? '${workout!.exercises.length} 个动作 · 已完成 ${workout!.completedSetCount} 组'
        : completed
        ? '今天的训练已经完成，做得很好'
        : scheduled
        ? '预计 ${event!.estimatedMinutes} 分钟 · 按自己的节奏完成'
        : '散步、拉伸或完整休息，都是有效训练的一部分';

    return AppSurface(
      color: AppColors.darkCard,
      borderColor: AppColors.darkCard,
      padding: const EdgeInsets.all(22),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              StatusPill(
                label: active
                    ? '进行中'
                    : completed
                    ? '已完成'
                    : scheduled
                    ? '今日训练'
                    : '恢复日',
                color: completed
                    ? const Color(0xFF83D7C5)
                    : active || scheduled
                    ? const Color(0xFFFF858A)
                    : const Color(0xFF83D7C5),
                icon: completed
                    ? Icons.check_circle_outline_rounded
                    : active || scheduled
                    ? Icons.bolt_rounded
                    : Icons.nightlight_round,
              ),
              const Spacer(),
              Icon(
                active || (scheduled && !completed)
                    ? Icons.fitness_center_rounded
                    : Icons.self_improvement_rounded,
                color: Colors.white24,
                size: 38,
              ),
            ],
          ),
          const SizedBox(height: 24),
          Text(
            title,
            style: Theme.of(context).textTheme.headlineMedium
                ?.copyWith(color: Colors.white),
          ),
          const SizedBox(height: 8),
          Text(
            detail,
            style: Theme.of(context).textTheme.bodyMedium
                ?.copyWith(color: Colors.white70),
          ),
          const SizedBox(height: 22),
          SizedBox(
            width: active || (scheduled && !completed) ? 170 : 150,
            child: FilledButton.icon(
              onPressed: submitting
                  ? null
                  : active
                  ? onContinue
                  : scheduled && !completed
                  ? onStart
                  : onOpenPlan,
              style: FilledButton.styleFrom(
                backgroundColor: Colors.white,
                foregroundColor: AppColors.ink,
              ),
              icon: Icon(
                active || (scheduled && !completed)
                    ? Icons.play_arrow_rounded
                    : Icons.calendar_month_rounded,
              ),
              label: Text(
                active
                    ? '继续训练'
                    : scheduled && !completed
                    ? '开始训练'
                    : '查看计划',
              ),
            ),
          ),
        ],
      ),
    );
  }
}
