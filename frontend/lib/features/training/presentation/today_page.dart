import 'package:flutter/material.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../domain/training_models.dart';
import 'training_controller.dart';
import 'workout_page.dart';

class TodayPage extends StatefulWidget {
  const TodayPage({
    super.key,
    required this.username,
    required this.controller,
    required this.onOpenNutrition,
    required this.onOpenPlan,
    required this.onOpenProgress,
    required this.onOpenAgent,
  });

  final String username;
  final TrainingController controller;
  final VoidCallback onOpenNutrition;
  final VoidCallback onOpenPlan;
  final VoidCallback onOpenProgress;
  final VoidCallback onOpenAgent;

  @override
  State<TodayPage> createState() => _TodayPageState();
}

class _TodayPageState extends State<TodayPage> {
  @override
  void initState() {
    super.initState();
    widget.controller.refresh();
  }

  Future<void> _openWorkout() async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => WorkoutPage(controller: widget.controller),
      ),
    );
  }

  Future<void> _start(CalendarEvent event) async {
    if (await widget.controller.start(event) && mounted) {
      await _openWorkout();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: ListenableBuilder(
          listenable: widget.controller,
          builder: (context, _) {
            final workout = widget.controller.activeWorkout;
            final nextEvent = widget.controller.events.isEmpty
                ? null
                : widget.controller.events.first;
            return RefreshIndicator(
              onRefresh: widget.controller.refresh,
              child: ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.fromLTRB(20, 22, 20, 30),
                children: [
                  _HomeHeader(
                    username: widget.username,
                    refreshing: widget.controller.loading,
                    onRefresh: widget.controller.refresh,
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
                        label: '饮食记录',
                        subtitle: '补充今天摄入',
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
                    title: '今日建议',
                    action: TextButton(
                      onPressed: widget.onOpenAgent,
                      child: const Text('问教练'),
                    ),
                  ),
                  const SizedBox(height: 10),
                  AppSurface(
                    onTap: widget.onOpenAgent,
                    child: Row(
                      children: [
                        Container(
                          width: 52,
                          height: 52,
                          decoration: BoxDecoration(
                            color: AppColors.mintSoft,
                            borderRadius: BorderRadius.circular(17),
                          ),
                          child: const Icon(
                            Icons.self_improvement_rounded,
                            color: AppColors.mint,
                            size: 27,
                          ),
                        ),
                        const SizedBox(width: 14),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                workout == null ? '给身体留出恢复空间' : '专注完成当前训练',
                                style: Theme.of(context).textTheme.titleMedium,
                              ),
                              const SizedBox(height: 4),
                              Text(
                                workout == null
                                    ? '睡眠、饮水和轻度活动同样属于计划的一部分。'
                                    : '按计划完成动作，不必为了数字牺牲动作质量。',
                                style: Theme.of(context).textTheme.bodyMedium
                                    ?.copyWith(color: AppColors.muted),
                              ),
                            ],
                          ),
                        ),
                        const Icon(
                          Icons.chevron_right_rounded,
                          color: AppColors.muted,
                        ),
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
