import 'package:flutter/material.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../domain/training_models.dart';

class ActivePlanDetailPage extends StatelessWidget {
  const ActivePlanDetailPage({super.key, required this.plan});

  final ActiveTrainingPlan plan;

  @override
  Widget build(BuildContext context) {
    final days = [...plan.days]
      ..sort((left, right) => left.dayIndex.compareTo(right.dayIndex));
    final weeklyMinutes = days.fold<int>(
      0,
      (total, day) => total + day.estimatedMinutes,
    );
    return Scaffold(
      appBar: AppBar(title: const Text('当前训练计划')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 32),
        children: [
          Text(plan.name, style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 8),
          Text(
            '每周 ${plan.weeklyFrequency} 次 · 共约 $weeklyMinutes 分钟',
            style: Theme.of(context).textTheme.bodyMedium
                ?.copyWith(color: AppColors.muted),
          ),
          const SizedBox(height: 8),
          const Text('以下是当前已启用的计划内容，可随时回来查看。'),
          const SizedBox(height: 20),
          if (days.isEmpty)
            const AppEmptyState(
              icon: Icons.event_busy_outlined,
              title: '当前计划暂无训练日',
              message: '请刷新计划页，或联系 AI 教练检查计划。',
            )
          else
            for (final day in days)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: AppSurface(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '第 ${day.dayIndex} 天 · ${day.name}',
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      const SizedBox(height: 4),
                      Text(
                        '约 ${day.estimatedMinutes} 分钟 · ${day.exercises.length} 个动作',
                        style: Theme.of(context).textTheme.bodyMedium
                            ?.copyWith(color: AppColors.muted),
                      ),
                      if (day.exercises.isNotEmpty) ...[
                        const Divider(height: 24),
                        for (
                          var index = 0;
                          index < day.exercises.length;
                          index++
                        )
                          _ExerciseRow(
                            number: index + 1,
                            exercise: day.exercises[index],
                          ),
                      ],
                    ],
                  ),
                ),
              ),
        ],
      ),
    );
  }
}

class _ExerciseRow extends StatelessWidget {
  const _ExerciseRow({required this.number, required this.exercise});

  final int number;
  final Map<String, dynamic> exercise;

  @override
  Widget build(BuildContext context) {
    final name = exercise['exercise_name'];
    final sets = exercise['target_sets'];
    final repMin = exercise['rep_min'];
    final repMax = exercise['rep_max'];
    final reps = repMin == repMax ? '$repMin' : '$repMin–$repMax';
    final details = <String>[
      if (sets != null && repMin != null && repMax != null) '$sets 组 × $reps 次',
      if (exercise['target_load_kg'] case final load?) '目标重量 $load kg',
      if (exercise['target_rir'] case final reserve?) '每组做完还能再做约 $reserve 次',
      if (exercise['rest_seconds'] case final rest?) '组间休息 $rest 秒',
    ];
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          CircleAvatar(
            radius: 14,
            backgroundColor: AppColors.primarySoft,
            child: Text('$number'),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  name is String && name.trim().isNotEmpty ? name : '动作名称暂不可用',
                  style: Theme.of(context).textTheme.titleSmall,
                ),
                if (details.isNotEmpty) ...[
                  const SizedBox(height: 3),
                  Text(
                    details.join(' · '),
                    style: Theme.of(context).textTheme.bodyMedium
                        ?.copyWith(color: AppColors.muted),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}
