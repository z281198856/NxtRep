import 'package:flutter/material.dart';

import '../../../core/widgets/app_widgets.dart';
import '../domain/training_models.dart';
import 'plan_controller.dart';

class CustomPlanPage extends StatefulWidget {
  const CustomPlanPage({super.key, required this.controller});

  final PlanController controller;

  @override
  State<CustomPlanPage> createState() => _CustomPlanPageState();
}

class _CustomPlanPageState extends State<CustomPlanPage> {
  static const _example = '周一：哑铃地板卧推 3×8-12，单臂哑铃划船 3×10\n周四：哑铃高脚杯深蹲 4×8';
  final _name = TextEditingController();
  final _planText = TextEditingController();
  String _mode = 'generate';
  String _goal = 'muscle_gain';
  String _equipment = 'barbell';
  int _days = 3;
  PlanDraft? _draft;

  @override
  void dispose() {
    _name.dispose();
    _planText.dispose();
    super.dispose();
  }

  Future<void> _createDraft() async {
    setState(() => _draft = null);
    final draft = _mode == 'generate'
        ? await widget.controller.generatePlan(
            goalType: _goal,
            daysPerWeek: _days,
            equipment: _equipment,
            name: _name.text.trim().isEmpty ? null : _name.text.trim(),
          )
        : await widget.controller.importPlanText(
            _planText.text,
            name: _name.text.trim().isEmpty ? null : _name.text.trim(),
          );
    if (mounted && draft != null) setState(() => _draft = draft);
  }

  Future<void> _activate() async {
    final draft = _draft;
    if (draft == null) return;
    if (await widget.controller.activateDraft(draft) && mounted) {
      Navigator.pop(context, true);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('自定义训练计划')),
      body: ListenableBuilder(
        listenable: widget.controller,
        builder: (context, _) => ListView(
          padding: const EdgeInsets.fromLTRB(20, 10, 20, 32),
          children: [
            SegmentedButton<String>(
              segments: const [
                ButtonSegment(
                  value: 'generate',
                  icon: Icon(Icons.auto_awesome_rounded),
                  label: Text('智能生成'),
                ),
                ButtonSegment(
                  value: 'import',
                  icon: Icon(Icons.text_snippet_outlined),
                  label: Text('文字导入'),
                ),
              ],
              selected: {_mode},
              onSelectionChanged: (value) {
                setState(() {
                  _mode = value.first;
                  _draft = null;
                });
              },
            ),
            const SizedBox(height: 18),
            TextField(
              controller: _name,
              decoration: const InputDecoration(
                labelText: '计划名称（可选）',
                hintText: '例如：秋季增肌计划',
              ),
            ),
            const SizedBox(height: 14),
            if (_mode == 'generate') ...[
              const Text('按目标、每周安排和器械匹配训练模板，预览后再启用。'),
              const SizedBox(height: 14),
              DropdownButtonFormField<String>(
                initialValue: _goal,
                decoration: const InputDecoration(labelText: '训练目标'),
                items: const [
                  DropdownMenuItem(value: 'muscle_gain', child: Text('增肌')),
                  DropdownMenuItem(
                    value: 'fat_loss_retain',
                    child: Text('减脂保肌'),
                  ),
                  DropdownMenuItem(value: 'recomposition', child: Text('塑形重组')),
                  DropdownMenuItem(value: 'maintain', child: Text('保持状态')),
                  DropdownMenuItem(value: 'strength', child: Text('力量')),
                ],
                onChanged: (value) => setState(() => _goal = value!),
              ),
              const SizedBox(height: 14),
              DropdownButtonFormField<int>(
                initialValue: _days,
                decoration: const InputDecoration(labelText: '每周训练'),
                items: [
                  for (var day = 1; day <= 7; day++)
                    DropdownMenuItem(value: day, child: Text('每周 $day 天')),
                ],
                onChanged: (value) => setState(() => _days = value!),
              ),
              if (_days >= 5) ...[
                const SizedBox(height: 8),
                const Text('5–7 天安排包含轻量恢复日，不会每天都安排高强度训练。'),
              ],
              if (_days == 1) ...[
                const SizedBox(height: 8),
                const Text('每周 1 天为低频起步安排，可在时间允许时增加频次。'),
              ],
              const SizedBox(height: 14),
              DropdownButtonFormField<String>(
                initialValue: _equipment,
                decoration: const InputDecoration(labelText: '训练条件'),
                items: const [
                  DropdownMenuItem(value: 'barbell', child: Text('杠铃与自由重量')),
                  DropdownMenuItem(value: 'cable', child: Text('绳索器械')),
                  DropdownMenuItem(value: 'bodyweight', child: Text('徒手训练')),
                  DropdownMenuItem(value: 'dumbbell', child: Text('仅哑铃')),
                ],
                onChanged: (value) => setState(() => _equipment = value!),
              ),
            ] else
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('按训练日填写动作库中的名称、组数和次数。无法识别的动作会提示具体行数。'),
                  const SizedBox(height: 12),
                  AppSurface(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text('格式示例'),
                        const SizedBox(height: 6),
                        const Text(_example),
                        Align(
                          alignment: Alignment.centerRight,
                          child: TextButton.icon(
                            onPressed: () => setState(() {
                              _planText.text = _example;
                              _draft = null;
                            }),
                            icon: const Icon(Icons.content_paste_rounded),
                            label: const Text('填入示例'),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _planText,
                    minLines: 7,
                    maxLines: 12,
                    onChanged: (_) => setState(() => _draft = null),
                    decoration: const InputDecoration(
                      labelText: '粘贴训练安排',
                      hintText: '例如：周一：哑铃地板卧推 3×8-12',
                      alignLabelWithHint: true,
                    ),
                  ),
                ],
              ),
            const SizedBox(height: 18),
            FilledButton.icon(
              onPressed:
                  widget.controller.submitting ||
                      (_mode == 'import' && _planText.text.trim().isEmpty)
                  ? null
                  : _createDraft,
              icon: widget.controller.submitting
                  ? const SizedBox.square(
                      dimension: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.auto_awesome_rounded),
              label: Text(_mode == 'generate' ? '生成计划草稿' : '解析训练安排'),
            ),
            if (widget.controller.errorMessage case final message?) ...[
              const SizedBox(height: 14),
              AppErrorCard(message: message),
            ],
            if (_draft case final draft?) ...[
              const SizedBox(height: 24),
              Text('计划预览', style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 10),
              AppSurface(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      draft.name,
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    const SizedBox(height: 5),
                    Text(
                      '每周 ${draft.weeklyFrequency} 天 · ${draft.days.length} 个训练日',
                    ),
                    if (_mode == 'import') ...[
                      const SizedBox(height: 5),
                      const Text('启用后从下一个周一开始排期；若当天是周一，则从当天开始。'),
                    ],
                    const Divider(height: 26),
                    for (final day in draft.days)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 12),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            CircleAvatar(
                              radius: 16,
                              child: Text('${day.dayIndex}'),
                            ),
                            const SizedBox(width: 10),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    day.name,
                                    style: Theme.of(context)
                                        .textTheme
                                        .titleSmall,
                                  ),
                                  Text(
                                    '${day.estimatedMinutes} 分钟 · ${day.exercises.length} 个动作',
                                  ),
                                  for (final exercise in day.exercises)
                                    if (exercise['exercise_name']
                                        case final String exerciseName)
                                      Padding(
                                        padding: const EdgeInsets.only(top: 5),
                                        child: Text(
                                          '$exerciseName · ${exercise['target_sets']} 组 × ${exercise['rep_min']}${exercise['rep_min'] == exercise['rep_max'] ? '' : '–${exercise['rep_max']}'} 次',
                                        ),
                                      ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      ),
                    FilledButton(
                      onPressed: widget.controller.submitting
                          ? null
                          : _activate,
                      child: const Text('校验并启用计划'),
                    ),
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
