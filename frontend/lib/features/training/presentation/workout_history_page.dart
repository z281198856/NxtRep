import 'package:flutter/material.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../domain/training_models.dart';
import 'plan_controller.dart';

class WorkoutHistoryPage extends StatelessWidget {
  const WorkoutHistoryPage({super.key, required this.controller});

  final PlanController controller;

  Future<void> _openDetails(
    BuildContext context,
    WorkoutHistoryItem item,
  ) async {
    final workout = await controller.loadWorkout(item.id);
    if (workout == null || !context.mounted) return;
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) =>
            WorkoutHistoryDetailPage(workout: workout, historyItem: item),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('训练历史')),
      body: ListenableBuilder(
        listenable: controller,
        builder: (context, _) => RefreshIndicator(
          onRefresh: controller.refresh,
          child: ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.fromLTRB(20, 8, 20, 32),
            children: [
              if (controller.errorMessage case final message?) ...[
                AppErrorCard(message: message),
                const SizedBox(height: 14),
              ],
              if (controller.loading && controller.history.isEmpty)
                const Padding(
                  padding: EdgeInsets.only(top: 100),
                  child: Center(child: CircularProgressIndicator()),
                )
              else if (controller.history.isEmpty)
                const AppEmptyState(
                  icon: Icons.history_rounded,
                  title: '还没有训练记录',
                  message: '完成第一场训练后，可以在这里查看组数、训练容量和动作详情。',
                )
              else ...[
                _HistorySummary(items: controller.history),
                const SizedBox(height: 22),
                for (final item in controller.history)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: _HistoryCard(
                      item: item,
                      loading: controller.detailLoading,
                      onTap: () => _openDetails(context, item),
                    ),
                  ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _HistorySummary extends StatelessWidget {
  const _HistorySummary({required this.items});

  final List<WorkoutHistoryItem> items;

  @override
  Widget build(BuildContext context) {
    final completedSets = items.fold<int>(
      0,
      (total, item) => total + item.completedSets,
    );
    final volume = items.fold<double>(
      0,
      (total, item) => total + item.totalVolumeKg,
    );
    return AppSurface(
      color: AppColors.darkCard,
      borderColor: AppColors.darkCard,
      padding: const EdgeInsets.all(20),
      child: Row(
        children: [
          Expanded(
            child: _SummaryMetric(label: '训练次数', value: '${items.length}'),
          ),
          const _SummaryDivider(),
          Expanded(
            child: _SummaryMetric(label: '完成组数', value: '$completedSets'),
          ),
          const _SummaryDivider(),
          Expanded(
            child: _SummaryMetric(label: '训练容量', value: _compactVolume(volume)),
          ),
        ],
      ),
    );
  }
}

class _SummaryMetric extends StatelessWidget {
  const _SummaryMetric({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(
          value,
          style: Theme.of(context).textTheme.titleLarge
              ?.copyWith(color: Colors.white),
        ),
        const SizedBox(height: 4),
        Text(
          label,
          style: Theme.of(context).textTheme.labelMedium
              ?.copyWith(color: Colors.white60),
        ),
      ],
    );
  }
}

class _SummaryDivider extends StatelessWidget {
  const _SummaryDivider();

  @override
  Widget build(BuildContext context) =>
      Container(width: 1, height: 38, color: Colors.white12);
}

class _HistoryCard extends StatelessWidget {
  const _HistoryCard({
    required this.item,
    required this.loading,
    required this.onTap,
  });

  final WorkoutHistoryItem item;
  final bool loading;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return AppSurface(
      onTap: loading ? null : onTap,
      padding: const EdgeInsets.all(16),
      child: Row(
        children: [
          Container(
            width: 50,
            height: 50,
            decoration: BoxDecoration(
              color: AppColors.primarySoft,
              borderRadius: BorderRadius.circular(17),
            ),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  '${item.date.day}',
                  style: const TextStyle(
                    color: AppColors.primary,
                    fontSize: 18,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                Text(
                  '${item.date.month}月',
                  style: const TextStyle(
                    color: AppColors.primary,
                    fontSize: 10,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  item.status == 'finished' ? '训练已完成' : '训练已结束',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 4),
                Text(
                  '${item.completedSets} 组 · ${_formatDuration(item.durationSeconds)} · '
                  '${item.totalVolumeKg.toStringAsFixed(0)} kg',
                  style: Theme.of(context).textTheme.bodyMedium
                      ?.copyWith(color: AppColors.muted),
                ),
              ],
            ),
          ),
          if (item.prCount > 0)
            StatusPill(
              label: '${item.prCount} PR',
              color: AppColors.amber,
              icon: Icons.emoji_events_rounded,
            )
          else
            const Icon(Icons.chevron_right_rounded, color: AppColors.muted),
        ],
      ),
    );
  }
}

class WorkoutHistoryDetailPage extends StatelessWidget {
  const WorkoutHistoryDetailPage({
    super.key,
    required this.workout,
    required this.historyItem,
  });

  final Workout workout;
  final WorkoutHistoryItem historyItem;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('训练详情')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 32),
        children: [
          AppSurface(
            color: AppColors.darkCard,
            borderColor: AppColors.darkCard,
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const StatusPill(
                  label: '已完成',
                  color: Color(0xFF83D7C5),
                  icon: Icons.check_circle_outline_rounded,
                ),
                const SizedBox(height: 18),
                Text(
                  '${historyItem.date.month} 月 ${historyItem.date.day} 日训练',
                  style: Theme.of(context).textTheme.headlineSmall
                      ?.copyWith(color: Colors.white),
                ),
                const SizedBox(height: 8),
                Text(
                  '${historyItem.completedSets} 组 · '
                  '${_formatDuration(historyItem.durationSeconds)} · '
                  '${historyItem.totalVolumeKg.toStringAsFixed(1)} kg',
                  style: Theme.of(context).textTheme.bodyMedium
                      ?.copyWith(color: Colors.white70),
                ),
              ],
            ),
          ),
          const SizedBox(height: 24),
          const SectionTitle(title: '动作记录'),
          const SizedBox(height: 12),
          if (workout.exercises.isEmpty)
            const AppEmptyState(
              icon: Icons.fitness_center_rounded,
              title: '没有动作记录',
              message: '这场训练没有保存动作组数。',
            )
          else
            for (final exercise in workout.exercises)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: _ExerciseHistoryCard(exercise: exercise),
              ),
        ],
      ),
    );
  }
}

class _ExerciseHistoryCard extends StatelessWidget {
  const _ExerciseHistoryCard({required this.exercise});

  final WorkoutExercise exercise;

  @override
  Widget build(BuildContext context) {
    return AppSurface(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  exercise.name,
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ),
              Text(
                '${exercise.sets.length} 组',
                style: Theme.of(context).textTheme.labelLarge
                    ?.copyWith(color: AppColors.muted),
              ),
            ],
          ),
          if (exercise.sets.isNotEmpty) ...[
            const Divider(height: 24),
            for (final set in exercise.sets)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 5),
                child: Row(
                  children: [
                    SizedBox(width: 44, child: Text('第 ${set.setIndex} 组')),
                    Expanded(
                      child: Text('${set.weightKg.toStringAsFixed(1)} kg'),
                    ),
                    Text('${set.reps} 次'),
                  ],
                ),
              ),
          ],
        ],
      ),
    );
  }
}

String _formatDuration(int? seconds) {
  if (seconds == null) return '未记录时长';
  final duration = Duration(seconds: seconds);
  final minutes = duration.inMinutes;
  if (minutes < 60) return '$minutes 分钟';
  final remainder = minutes % 60;
  return remainder == 0
      ? '${duration.inHours} 小时'
      : '${duration.inHours} 小时 $remainder 分';
}

String _compactVolume(double value) {
  if (value >= 1000) return '${(value / 1000).toStringAsFixed(1)}t';
  return '${value.toStringAsFixed(0)}kg';
}
