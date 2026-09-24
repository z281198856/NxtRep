import 'package:flutter/material.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../domain/training_models.dart';
import 'plan_controller.dart';

const goalLabels = <String, String>{
  'muscle_gain': '增肌',
  'fat_loss_retain': '减脂保肌',
  'recomposition': '塑形重组',
  'maintain': '保持状态',
  'strength': '力量',
};

const equipmentLabels = <String, String>{
  'bodyweight': '徒手',
  'dumbbell': '哑铃',
  'barbell': '杠铃',
  'cable': '绳索',
};

List<TrainingTemplate> filterTrainingTemplates(
  List<TrainingTemplate> templates, {
  String? goal,
  String? equipment,
  int? days,
}) {
  final matches = templates.where((template) {
    if (goal != null && !template.goalTypes.contains(goal)) return false;
    if (days != null && template.daysPerWeek != days) return false;
    if (equipment != null &&
        (!template.equipment.contains(equipment) ||
            template.equipment.any(
              (item) => item != equipment && item != 'bodyweight',
            ))) {
      return false;
    }
    return true;
  }).toList();
  const gears = ['bodyweight', 'dumbbell', 'barbell', 'cable'];
  const goals = ['muscle_gain', 'fat_loss_retain', 'strength'];
  int gearRank(TrainingTemplate template) {
    for (var index = 0; index < gears.length; index++) {
      if (template.equipment.contains(gears[index]) &&
          template.equipment.every(
            (item) => item == gears[index] || item == 'bodyweight',
          )) {
        return index;
      }
    }
    return gears.length;
  }

  int goalRank(TrainingTemplate template) {
    for (var index = 0; index < goals.length; index++) {
      if (template.goalTypes.contains(goals[index])) return index;
    }
    return goals.length;
  }

  matches.sort((first, second) {
    final frequency = first.daysPerWeek.compareTo(second.daysPerWeek);
    if (frequency != 0) return frequency;
    final gear = gearRank(first).compareTo(gearRank(second));
    if (gear != 0) return gear;
    final goal = goalRank(first).compareTo(goalRank(second));
    return goal != 0 ? goal : first.name.compareTo(second.name);
  });
  return matches;
}

class TemplateCatalogPage extends StatefulWidget {
  const TemplateCatalogPage({super.key, required this.controller});

  final PlanController controller;

  @override
  State<TemplateCatalogPage> createState() => _TemplateCatalogPageState();
}

class _TemplateCatalogPageState extends State<TemplateCatalogPage> {
  String? _goal;
  String? _equipment;
  int? _days;

  Future<void> _open(TrainingTemplate template) async {
    final activated = await Navigator.of(context).push<bool>(
      MaterialPageRoute<bool>(
        builder: (_) => TemplateDetailPage(
          controller: widget.controller,
          template: template,
        ),
      ),
    );
    if (activated == true && mounted) Navigator.pop(context, true);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('全部训练计划')),
      body: ListenableBuilder(
        listenable: widget.controller,
        builder: (context, _) {
          final templates = filterTrainingTemplates(
            widget.controller.templates,
            goal: _goal,
            equipment: _equipment,
            days: _days,
          );
          return ListView(
            padding: const EdgeInsets.fromLTRB(20, 10, 20, 32),
            children: [
              Text(
                '按目标、器械和每周天数筛选，点开计划查看动作后再启用。',
                style: Theme.of(context).textTheme.bodyMedium,
              ),
              const SizedBox(height: 16),
              DropdownButtonFormField<String>(
                key: const ValueKey('catalog-goal'),
                initialValue: _goal,
                decoration: const InputDecoration(labelText: '训练目标'),
                items: [
                  const DropdownMenuItem(value: null, child: Text('全部目标')),
                  for (final entry in goalLabels.entries)
                    DropdownMenuItem(
                      value: entry.key,
                      child: Text(entry.value),
                    ),
                ],
                onChanged: (value) => setState(() => _goal = value),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                key: const ValueKey('catalog-equipment'),
                initialValue: _equipment,
                decoration: const InputDecoration(labelText: '训练器械'),
                items: [
                  const DropdownMenuItem(value: null, child: Text('全部器械')),
                  for (final entry in equipmentLabels.entries)
                    DropdownMenuItem(
                      value: entry.key,
                      child: Text(entry.value),
                    ),
                ],
                onChanged: (value) => setState(() => _equipment = value),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<int>(
                key: const ValueKey('catalog-days'),
                initialValue: _days,
                decoration: const InputDecoration(labelText: '每周训练'),
                items: [
                  const DropdownMenuItem(value: null, child: Text('全部频次')),
                  for (var day = 1; day <= 7; day++)
                    DropdownMenuItem(value: day, child: Text('每周 $day 天')),
                ],
                onChanged: (value) => setState(() => _days = value),
              ),
              const SizedBox(height: 22),
              SectionTitle(title: '找到 ${templates.length} 套计划'),
              const SizedBox(height: 12),
              if (templates.isEmpty)
                const AppEmptyState(
                  icon: Icons.search_off_rounded,
                  title: '没有匹配的计划',
                  message: '调整目标、器械或每周天数再看看。',
                ),
              for (final template in templates)
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: AppSurface(
                    onTap: () => _open(template),
                    child: Row(
                      children: [
                        const Icon(
                          Icons.calendar_month_rounded,
                          color: AppColors.primary,
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                template.name,
                                style: Theme.of(context).textTheme.titleMedium,
                              ),
                              const SizedBox(height: 4),
                              Text(
                                '每周 ${template.daysPerWeek} 天 · 约 ${template.durationMinutes} 分钟 · ${template.goalTypes.map((item) => goalLabels[item] ?? item).join(' / ')}',
                                style: Theme.of(context).textTheme.bodySmall,
                              ),
                            ],
                          ),
                        ),
                        const Icon(Icons.chevron_right_rounded),
                      ],
                    ),
                  ),
                ),
            ],
          );
        },
      ),
    );
  }
}

class TemplateDetailPage extends StatefulWidget {
  const TemplateDetailPage({
    super.key,
    required this.controller,
    required this.template,
  });

  final PlanController controller;
  final TrainingTemplate template;

  @override
  State<TemplateDetailPage> createState() => _TemplateDetailPageState();
}

class _TemplateDetailPageState extends State<TemplateDetailPage> {
  late Future<TrainingTemplateDetail> _detail;

  @override
  void initState() {
    super.initState();
    _detail = widget.controller.getTemplateDetail(widget.template.id);
  }

  Future<void> _activate() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('启用“${widget.template.name}”？'),
        content: const Text('确认后将生成未来四周的训练日历。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('再看看'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('确认启用'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    final activated = await widget.controller.activateTemplate(widget.template);
    if (mounted && activated) Navigator.pop(context, true);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('计划预览')),
      body: FutureBuilder<TrainingTemplateDetail>(
        future: _detail,
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return Center(
              child: AppEmptyState(
                icon: Icons.error_outline_rounded,
                title: '计划预览加载失败',
                message: '${snapshot.error}',
              ),
            );
          }
          if (!snapshot.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          final detail = snapshot.data!;
          return ListenableBuilder(
            listenable: widget.controller,
            builder: (context, _) => ListView(
              padding: const EdgeInsets.fromLTRB(20, 10, 20, 32),
              children: [
                Text(
                  detail.template.name,
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 8),
                Text(
                  '目标：${detail.template.goalTypes.map((item) => goalLabels[item] ?? item).join(' / ')}\n'
                  '每周 ${detail.template.daysPerWeek} 天 · 单次约 ${detail.template.durationMinutes} 分钟',
                ),
                if (detail.template.daysPerWeek >= 5) ...[
                  const SizedBox(height: 8),
                  const Text('含轻量恢复日。'),
                ],
                const SizedBox(height: 18),
                for (final day in detail.days)
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
                            '${day.estimatedMinutes} 分钟 · ${day.exercises.length} 个动作',
                          ),
                          const Divider(height: 24),
                          for (final exercise in day.exercises)
                            Padding(
                              padding: const EdgeInsets.only(bottom: 10),
                              child: Text(
                                '${exercise['exercise_name'] ?? '动作不可用'}  ·  ${exercise['target_sets']} 组 × ${exercise['rep_min']}–${exercise['rep_max']} 次'
                                '${exercise['target_rir'] == null ? '' : '  ·  保留 ${exercise['target_rir']} 次余力'}',
                              ),
                            ),
                        ],
                      ),
                    ),
                  ),
                const SizedBox(height: 10),
                FilledButton(
                  onPressed: widget.controller.submitting ? null : _activate,
                  child: widget.controller.submitting
                      ? const SizedBox.square(
                          dimension: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Text('启用这套计划'),
                ),
                if (widget.controller.errorMessage case final message?) ...[
                  const SizedBox(height: 12),
                  AppErrorCard(message: message),
                ],
              ],
            ),
          );
        },
      ),
    );
  }
}
