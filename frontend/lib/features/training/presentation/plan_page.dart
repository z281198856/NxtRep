import 'package:flutter/material.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../domain/training_models.dart';
import 'custom_plan_page.dart';
import 'plan_controller.dart';
import 'template_catalog_page.dart';
import 'workout_history_page.dart';

class PlanPage extends StatefulWidget {
  const PlanPage({
    super.key,
    required this.controller,
    required this.onAskCoach,
    required this.onOpenExerciseLibrary,
  });

  final PlanController controller;
  final Future<void> Function(String prompt) onAskCoach;
  final VoidCallback onOpenExerciseLibrary;

  @override
  State<PlanPage> createState() => _PlanPageState();
}

class _PlanPageState extends State<PlanPage> {
  late DateTime _selectedDate;

  @override
  void initState() {
    super.initState();
    final now = DateTime.now();
    _selectedDate = DateTime(now.year, now.month, now.day);
    widget.controller.refresh();
  }

  CalendarEvent? _selectedEvent(List<CalendarEvent> events) {
    for (final event in events) {
      final date = event.scheduledDate.toLocal();
      if (date.year == _selectedDate.year &&
          date.month == _selectedDate.month &&
          date.day == _selectedDate.day) {
        return event;
      }
    }
    return null;
  }

  Future<void> _askForPlan(String mode) =>
      widget.onAskCoach('请根据我的目标和每周训练频率，为我生成一份$mode训练计划草稿。');

  Future<void> _openTemplateDetail(TrainingTemplate template) async {
    await Navigator.of(context).push<bool>(
      MaterialPageRoute<bool>(
        builder: (_) => TemplateDetailPage(
          controller: widget.controller,
          template: template,
        ),
      ),
    );
  }

  Future<void> _openCatalog() async {
    await Navigator.of(context).push<bool>(
      MaterialPageRoute<bool>(
        builder: (_) => TemplateCatalogPage(controller: widget.controller),
      ),
    );
  }

  Future<void> _openHistory() => Navigator.of(context).push(
    MaterialPageRoute<void>(
      builder: (_) => WorkoutHistoryPage(controller: widget.controller),
    ),
  );

  Future<void> _openCustomPlan() async {
    final changed = await Navigator.of(context).push<bool>(
      MaterialPageRoute<bool>(
        builder: (_) => CustomPlanPage(controller: widget.controller),
      ),
    );
    if (changed == true) await widget.controller.refresh();
  }

  Future<void> _createCalendarEvent() async {
    final input = await showModalBottomSheet<_CalendarEventInput>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _CreateCalendarEventSheet(date: _selectedDate),
    );
    if (input == null) return;
    final saved = await widget.controller.createCalendarEvent(
      date: _selectedDate,
      title: input.title,
      estimatedMinutes: input.minutes,
    );
    if (saved && mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('训练已加入日历')));
    }
  }

  Future<void> _adjustEvent(CalendarEvent event) async {
    final action = await showModalBottomSheet<_CalendarAdjustmentInput>(
      context: context,
      builder: (_) => _CalendarAdjustmentSheet(event: event),
    );
    if (action == null) return;
    final saved = action.targetMinutes == null
        ? await widget.controller.rescheduleEvent(
            event: event,
            strategy: action.strategy,
            targetDate: action.targetDate,
          )
        : await widget.controller.compressEvent(
            event,
            targetMinutes: action.targetMinutes!,
          );
    if (saved && mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('训练日历已更新')));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: ListenableBuilder(
          listenable: widget.controller,
          builder: (context, _) {
            final plan = widget.controller.activePlan;
            final event = _selectedEvent(widget.controller.events);
            return RefreshIndicator(
              onRefresh: widget.controller.refresh,
              child: ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.fromLTRB(20, 22, 20, 30),
                children: [
                  AppPageHeader(
                    title: '训练计划',
                    subtitle: '把每次训练安排得清楚、可执行',
                    trailing: IconButton.filledTonal(
                      tooltip: '刷新',
                      onPressed: widget.controller.loading
                          ? null
                          : widget.controller.refresh,
                      icon: const Icon(Icons.refresh_rounded),
                    ),
                  ),
                  const SizedBox(height: 22),
                  if (widget.controller.errorMessage case final message?) ...[
                    AppErrorCard(message: message),
                    const SizedBox(height: 14),
                  ],
                  _PlanSummaryCard(plan: plan),
                  const SizedBox(height: 12),
                  AppSurface(
                    onTap: widget.controller.submitting
                        ? null
                        : _openCustomPlan,
                    padding: const EdgeInsets.all(17),
                    child: const Row(
                      children: [
                        Icon(Icons.tune_rounded, color: AppColors.primary),
                        SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text('自定义训练计划'),
                              SizedBox(height: 3),
                              Text('智能生成，或从文字训练表导入'),
                            ],
                          ),
                        ),
                        Icon(Icons.chevron_right_rounded),
                      ],
                    ),
                  ),
                  if (plan == null) ...[
                    const SizedBox(height: 28),
                    SectionTitle(
                      title: '按目标推荐',
                      action: TextButton(
                        onPressed: widget.controller.submitting
                            ? null
                            : _openCatalog,
                        child: Text(
                          '全部 ${widget.controller.templates.length} 套',
                        ),
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      '增肌塑形、减脂保肌与力量基础；点开可预览每一天的动作。',
                      style: Theme.of(context).textTheme.bodyMedium
                          ?.copyWith(color: AppColors.muted),
                    ),
                    const SizedBox(height: 12),
                    if (!widget.controller.loading &&
                        widget.controller.templates.isEmpty)
                      const AppEmptyState(
                        icon: Icons.event_busy_rounded,
                        title: '暂无官方计划',
                        message: '可以先让 AI 教练根据你的条件生成计划草稿。',
                      )
                    else
                      ...widget.controller.recommendedTemplates.map(
                        (template) => Padding(
                          padding: const EdgeInsets.only(bottom: 10),
                          child: _TemplatePlanCard(
                            template: template,
                            loading:
                                widget.controller.activatingTemplateId ==
                                template.id,
                            enabled: !widget.controller.submitting,
                            onTap: () => _openTemplateDetail(template),
                          ),
                        ),
                      ),
                  ] else ...[
                    const SizedBox(height: 16),
                    _ActivePlanOverview(plan: plan),
                    const SizedBox(height: 12),
                    OutlinedButton.icon(
                      onPressed: _openCatalog,
                      icon: const Icon(Icons.view_list_rounded),
                      label: Text(
                        '浏览全部 ${widget.controller.templates.length} 套计划',
                      ),
                    ),
                  ],
                  const SizedBox(height: 24),
                  _WeekStrip(
                    selectedDate: _selectedDate,
                    events: widget.controller.events,
                    onSelected: (date) => setState(() => _selectedDate = date),
                  ),
                  const SizedBox(height: 22),
                  SectionTitle(
                    title: '当日安排',
                    action: Text(
                      '${_selectedDate.month} 月 ${_selectedDate.day} 日',
                      style: Theme.of(context).textTheme.labelLarge
                          ?.copyWith(color: AppColors.muted),
                    ),
                  ),
                  const SizedBox(height: 11),
                  if (widget.controller.loading && plan == null)
                    const AppSurface(
                      child: Center(
                        child: Padding(
                          padding: EdgeInsets.all(24),
                          child: CircularProgressIndicator(),
                        ),
                      ),
                    )
                  else
                    _DayPlanCard(
                      event: event,
                      onCreate: () => _askForPlan('适合当前条件的'),
                      onCreateManual: _createCalendarEvent,
                      onAdjust: event == null
                          ? null
                          : () => _adjustEvent(event),
                    ),
                  const SizedBox(height: 24),
                  AppSurface(
                    onTap: widget.onOpenExerciseLibrary,
                    padding: const EdgeInsets.all(17),
                    child: Row(
                      children: [
                        Container(
                          width: 52,
                          height: 52,
                          decoration: BoxDecoration(
                            color: AppColors.indigoSoft,
                            borderRadius: BorderRadius.circular(17),
                          ),
                          child: const Icon(
                            Icons.accessibility_new_rounded,
                            color: AppColors.indigo,
                          ),
                        ),
                        const SizedBox(width: 14),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                '动作库',
                                style: Theme.of(context).textTheme.titleMedium,
                              ),
                              const SizedBox(height: 3),
                              Text(
                                '查看动作步骤、替代动作和历史训练',
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
                  const SizedBox(height: 28),
                  const SectionTitle(title: '选择训练方式'),
                  const SizedBox(height: 6),
                  Text(
                    '只保留两种清晰选择，AI 会结合你的目标和频率调整内容。',
                    style: Theme.of(context).textTheme.bodyMedium
                        ?.copyWith(color: AppColors.muted),
                  ),
                  const SizedBox(height: 12),
                  _ModePlanCard(
                    icon: Icons.accessibility_new_rounded,
                    title: '徒手训练',
                    description: '不依赖器械，适合居家、出差或刚开始训练。',
                    color: AppColors.mint,
                    onTap: () => _askForPlan('徒手'),
                  ),
                  const SizedBox(height: 12),
                  _ModePlanCard(
                    icon: Icons.fitness_center_rounded,
                    title: '健身房器械训练',
                    description: '使用哑铃、杠铃、绳索器械和深蹲架。',
                    color: AppColors.indigo,
                    onTap: () => _askForPlan('健身房器械'),
                  ),
                  if (widget.controller.events.length > 1) ...[
                    const SizedBox(height: 28),
                    const SectionTitle(title: '接下来'),
                    const SizedBox(height: 12),
                    ...widget.controller.events
                        .where((item) => item != event)
                        .take(4)
                        .map(_UpcomingEventTile.new),
                  ],
                  const SizedBox(height: 28),
                  SectionTitle(
                    title: '训练历史',
                    action: TextButton(
                      onPressed: _openHistory,
                      child: const Text('查看全部'),
                    ),
                  ),
                  const SizedBox(height: 10),
                  if (widget.controller.history.isEmpty)
                    AppSurface(
                      onTap: _openHistory,
                      child: const Row(
                        children: [
                          Icon(Icons.history_rounded, color: AppColors.muted),
                          SizedBox(width: 12),
                          Expanded(child: Text('完成第一场训练后，记录会显示在这里')),
                          Icon(
                            Icons.chevron_right_rounded,
                            color: AppColors.muted,
                          ),
                        ],
                      ),
                    )
                  else
                    ...widget.controller.history
                        .take(3)
                        .map(
                          (item) => Padding(
                            padding: const EdgeInsets.only(bottom: 10),
                            child: _HistoryPreviewTile(
                              item: item,
                              onTap: _openHistory,
                            ),
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

class _TemplatePlanCard extends StatelessWidget {
  const _TemplatePlanCard({
    required this.template,
    required this.loading,
    required this.enabled,
    required this.onTap,
  });

  final TrainingTemplate template;
  final bool loading;
  final bool enabled;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return AppSurface(
      onTap: enabled ? onTap : null,
      padding: const EdgeInsets.all(16),
      child: Row(
        children: [
          Container(
            width: 52,
            height: 52,
            decoration: BoxDecoration(
              color: AppColors.primarySoft,
              borderRadius: BorderRadius.circular(17),
            ),
            child: const Icon(
              Icons.calendar_month_rounded,
              color: AppColors.primary,
            ),
          ),
          const SizedBox(width: 14),
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
                  '每周 ${template.daysPerWeek} 次 · 每次约 ${template.durationMinutes} 分钟',
                  style: Theme.of(context).textTheme.bodyMedium
                      ?.copyWith(color: AppColors.muted),
                ),
              ],
            ),
          ),
          if (loading)
            const SizedBox.square(
              dimension: 22,
              child: CircularProgressIndicator(strokeWidth: 2.4),
            )
          else
            const Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.visibility_outlined, color: AppColors.primary),
                Text('预览'),
              ],
            ),
        ],
      ),
    );
  }
}

class _ActivePlanOverview extends StatelessWidget {
  const _ActivePlanOverview({required this.plan});

  final ActiveTrainingPlan plan;

  @override
  Widget build(BuildContext context) {
    return AppSurface(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('本周安排', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final day in plan.days)
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 9,
                  ),
                  decoration: BoxDecoration(
                    color: AppColors.indigoSoft,
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: Text(
                    '${day.name} · ${day.exercises.length} 个动作',
                    style: const TextStyle(
                      color: AppColors.indigo,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _HistoryPreviewTile extends StatelessWidget {
  const _HistoryPreviewTile({required this.item, required this.onTap});

  final WorkoutHistoryItem item;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return AppSurface(
      onTap: onTap,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      child: Row(
        children: [
          Container(
            width: 46,
            height: 46,
            decoration: BoxDecoration(
              color: AppColors.mintSoft,
              borderRadius: BorderRadius.circular(15),
            ),
            child: const Icon(Icons.check_rounded, color: AppColors.mint),
          ),
          const SizedBox(width: 13),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${item.date.month} 月 ${item.date.day} 日训练',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 3),
                Text(
                  '${item.completedSets} 组 · ${_formatHistoryDuration(item.durationSeconds)} · '
                  '${item.totalVolumeKg.toStringAsFixed(0)} kg',
                  style: Theme.of(context).textTheme.labelMedium,
                ),
              ],
            ),
          ),
          const Icon(Icons.chevron_right_rounded, color: AppColors.muted),
        ],
      ),
    );
  }
}

class _PlanSummaryCard extends StatelessWidget {
  const _PlanSummaryCard({required this.plan});

  final ActiveTrainingPlan? plan;

  @override
  Widget build(BuildContext context) {
    return AppSurface(
      color: AppColors.darkCard,
      borderColor: AppColors.darkCard,
      padding: const EdgeInsets.all(22),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const StatusPill(
            label: '当前计划',
            color: Color(0xFFFF858A),
            icon: Icons.bolt_rounded,
          ),
          const SizedBox(height: 20),
          Text(
            plan?.name ?? '还没有启用计划',
            style: Theme.of(context).textTheme.headlineSmall
                ?.copyWith(color: Colors.white),
          ),
          const SizedBox(height: 7),
          Text(
            plan == null
                ? '选择一种训练方式，让 AI 教练为你生成可确认的计划草稿。'
                : '每周 ${plan!.weeklyFrequency} 次 · 按日历稳步完成',
            style: Theme.of(context).textTheme.bodyMedium
                ?.copyWith(color: Colors.white70),
          ),
        ],
      ),
    );
  }
}

class _WeekStrip extends StatelessWidget {
  const _WeekStrip({
    required this.selectedDate,
    required this.events,
    required this.onSelected,
  });

  final DateTime selectedDate;
  final List<CalendarEvent> events;
  final ValueChanged<DateTime> onSelected;

  bool _hasEvent(DateTime day) => events.any((event) {
    final date = event.scheduledDate.toLocal();
    return date.year == day.year &&
        date.month == day.month &&
        date.day == day.day;
  });

  @override
  Widget build(BuildContext context) {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final start = today.subtract(Duration(days: today.weekday - 1));
    const weekdays = ['一', '二', '三', '四', '五', '六', '日'];
    return AppSurface(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 10),
      child: Row(
        children: [
          for (var index = 0; index < 7; index++)
            Expanded(
              child: _DayChip(
                weekday: weekdays[index],
                date: start.add(Duration(days: index)),
                selected: _sameDay(
                  selectedDate,
                  start.add(Duration(days: index)),
                ),
                hasEvent: _hasEvent(start.add(Duration(days: index))),
                onTap: onSelected,
              ),
            ),
        ],
      ),
    );
  }
}

class _DayChip extends StatelessWidget {
  const _DayChip({
    required this.weekday,
    required this.date,
    required this.selected,
    required this.hasEvent,
    required this.onTap,
  });

  final String weekday;
  final DateTime date;
  final bool selected;
  final bool hasEvent;
  final ValueChanged<DateTime> onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      selected: selected,
      label: '${date.month}月${date.day}日${hasEvent ? '，有训练安排' : ''}',
      child: InkWell(
        onTap: () => onTap(date),
        borderRadius: BorderRadius.circular(16),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 180),
          padding: const EdgeInsets.symmetric(vertical: 9),
          decoration: BoxDecoration(
            color: selected ? AppColors.primarySoft : Colors.transparent,
            borderRadius: BorderRadius.circular(16),
          ),
          child: Column(
            children: [
              Text(
                weekday,
                style: TextStyle(
                  color: selected ? AppColors.primary : AppColors.muted,
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 5),
              Text(
                '${date.day}',
                style: TextStyle(
                  color: selected ? AppColors.primary : AppColors.ink,
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 5),
              Container(
                width: 5,
                height: 5,
                decoration: BoxDecoration(
                  color: hasEvent ? AppColors.primary : Colors.transparent,
                  shape: BoxShape.circle,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _DayPlanCard extends StatelessWidget {
  const _DayPlanCard({
    required this.event,
    required this.onCreate,
    required this.onCreateManual,
    required this.onAdjust,
  });

  final CalendarEvent? event;
  final VoidCallback onCreate;
  final VoidCallback onCreateManual;
  final VoidCallback? onAdjust;

  @override
  Widget build(BuildContext context) {
    return AppSurface(
      padding: const EdgeInsets.all(20),
      child: event == null
          ? Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    const Icon(
                      Icons.event_available_rounded,
                      color: AppColors.mint,
                    ),
                    const SizedBox(width: 9),
                    Text(
                      '暂无安排',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                  ],
                ),
                const SizedBox(height: 9),
                Text(
                  '这一天还没有训练，可以休息或让 AI 教练补充计划。',
                  style: Theme.of(context).textTheme.bodyMedium
                      ?.copyWith(color: AppColors.muted),
                ),
                const SizedBox(height: 16),
                OutlinedButton.icon(
                  onPressed: onCreate,
                  icon: const Icon(Icons.auto_awesome_rounded),
                  label: const Text('让 AI 帮我安排'),
                ),
                TextButton.icon(
                  onPressed: onCreateManual,
                  icon: const Icon(Icons.add_rounded),
                  label: const Text('手动加入日历'),
                ),
              ],
            )
          : Row(
              children: [
                Container(
                  width: 54,
                  height: 54,
                  decoration: BoxDecoration(
                    color: AppColors.primarySoft,
                    borderRadius: BorderRadius.circular(18),
                  ),
                  child: const Icon(
                    Icons.bolt_rounded,
                    color: AppColors.primary,
                  ),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        event!.title,
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      const SizedBox(height: 5),
                      Text(
                        '预计 ${event!.estimatedMinutes} 分钟',
                        style: Theme.of(context).textTheme.bodyMedium
                            ?.copyWith(color: AppColors.muted),
                      ),
                    ],
                  ),
                ),
                if (event!.actualWorkoutId != null)
                  const StatusPill(
                    label: '已完成',
                    color: AppColors.mint,
                    icon: Icons.check_rounded,
                  )
                else
                  IconButton(
                    tooltip: '调整训练',
                    onPressed: onAdjust,
                    icon: const Icon(Icons.edit_calendar_outlined),
                  ),
              ],
            ),
    );
  }
}

class _CalendarEventInput {
  const _CalendarEventInput({required this.title, required this.minutes});

  final String title;
  final int minutes;
}

class _CreateCalendarEventSheet extends StatefulWidget {
  const _CreateCalendarEventSheet({required this.date});

  final DateTime date;

  @override
  State<_CreateCalendarEventSheet> createState() =>
      _CreateCalendarEventSheetState();
}

class _CreateCalendarEventSheetState extends State<_CreateCalendarEventSheet> {
  final _title = TextEditingController(text: '自主训练');
  int _minutes = 60;

  @override
  void dispose() {
    _title.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.fromLTRB(
        20,
        16,
        20,
        MediaQuery.viewInsetsOf(context).bottom + 22,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('加入训练日历', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 6),
          Text('${widget.date.month} 月 ${widget.date.day} 日'),
          const SizedBox(height: 16),
          TextField(
            controller: _title,
            autofocus: true,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(labelText: '训练名称'),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<int>(
            initialValue: _minutes,
            decoration: const InputDecoration(labelText: '预计时间'),
            items: const [30, 45, 60, 75, 90]
                .map(
                  (minutes) => DropdownMenuItem(
                    value: minutes,
                    child: Text('$minutes 分钟'),
                  ),
                )
                .toList(growable: false),
            onChanged: (value) => setState(() => _minutes = value!),
          ),
          const SizedBox(height: 18),
          FilledButton(
            onPressed: _title.text.trim().isEmpty
                ? null
                : () => Navigator.pop(
                    context,
                    _CalendarEventInput(
                      title: _title.text.trim(),
                      minutes: _minutes,
                    ),
                  ),
            child: const Text('加入日历'),
          ),
        ],
      ),
    );
  }
}

class _CalendarAdjustmentInput {
  const _CalendarAdjustmentInput({
    required this.strategy,
    this.targetDate,
    this.targetMinutes,
  });

  final String strategy;
  final DateTime? targetDate;
  final int? targetMinutes;
}

class _CalendarAdjustmentSheet extends StatelessWidget {
  const _CalendarAdjustmentSheet({required this.event});

  final CalendarEvent event;

  Future<void> _move(BuildContext context) async {
    final initial = event.scheduledDate.add(const Duration(days: 1));
    final date = await showDatePicker(
      context: context,
      initialDate: initial,
      firstDate: DateTime.now(),
      lastDate: DateTime.now().add(const Duration(days: 90)),
    );
    if (date != null && context.mounted) {
      Navigator.pop(
        context,
        _CalendarAdjustmentInput(strategy: 'shift', targetDate: date),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              '调整 ${event.title}',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 12),
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.event_repeat_rounded),
              title: const Text('改到其他日期'),
              subtitle: const Text('保留训练内容，只调整日期'),
              onTap: () => _move(context),
            ),
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.compress_rounded),
              title: const Text('压缩为 45 分钟'),
              subtitle: const Text('后端会减少总时长并保留重点动作'),
              onTap: () => Navigator.pop(
                context,
                const _CalendarAdjustmentInput(
                  strategy: 'compress',
                  targetMinutes: 45,
                ),
              ),
            ),
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.compress_rounded),
              title: const Text('压缩为 30 分钟'),
              onTap: () => Navigator.pop(
                context,
                const _CalendarAdjustmentInput(
                  strategy: 'compress',
                  targetMinutes: 30,
                ),
              ),
            ),
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.event_busy_outlined),
              title: const Text('跳过本次训练'),
              onTap: () => Navigator.pop(
                context,
                const _CalendarAdjustmentInput(strategy: 'skip'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ModePlanCard extends StatelessWidget {
  const _ModePlanCard({
    required this.icon,
    required this.title,
    required this.description,
    required this.color,
    required this.onTap,
  });

  final IconData icon;
  final String title;
  final String description;
  final Color color;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return AppSurface(
      onTap: onTap,
      child: Row(
        children: [
          Container(
            width: 54,
            height: 54,
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(18),
            ),
            child: Icon(icon, color: color, size: 27),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 4),
                Text(
                  description,
                  style: Theme.of(context).textTheme.bodyMedium
                      ?.copyWith(color: AppColors.muted),
                ),
              ],
            ),
          ),
          const Icon(Icons.chevron_right_rounded, color: AppColors.muted),
        ],
      ),
    );
  }
}

class _UpcomingEventTile extends StatelessWidget {
  const _UpcomingEventTile(this.event);

  final CalendarEvent event;

  @override
  Widget build(BuildContext context) {
    final date = event.scheduledDate.toLocal();
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: AppSurface(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        child: Row(
          children: [
            Container(
              width: 43,
              height: 43,
              decoration: BoxDecoration(
                color: AppColors.indigoSoft,
                borderRadius: BorderRadius.circular(14),
              ),
              child: Center(
                child: Text(
                  '${date.day}',
                  style: const TextStyle(
                    color: AppColors.indigo,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
            ),
            const SizedBox(width: 13),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    event.title,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 3),
                  Text(
                    '${date.month} 月 ${date.day} 日 · ${event.estimatedMinutes} 分钟',
                    style: Theme.of(context).textTheme.labelMedium,
                  ),
                ],
              ),
            ),
            if (event.actualWorkoutId != null)
              const Icon(Icons.check_circle_rounded, color: AppColors.mint),
          ],
        ),
      ),
    );
  }
}

bool _sameDay(DateTime a, DateTime b) =>
    a.year == b.year && a.month == b.month && a.day == b.day;

String _formatHistoryDuration(int? seconds) {
  if (seconds == null) return '未记录时长';
  final minutes = (seconds / 60).round();
  if (minutes < 60) return '$minutes 分钟';
  final hours = minutes ~/ 60;
  final remainder = minutes % 60;
  return remainder == 0 ? '$hours 小时' : '$hours 小时 $remainder 分';
}
