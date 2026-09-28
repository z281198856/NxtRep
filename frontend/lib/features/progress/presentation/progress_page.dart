import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../domain/body_models.dart';
import 'navy_body_fat_sheet.dart';
import 'progress_controller.dart';

class ProgressPage extends StatefulWidget {
  const ProgressPage({
    super.key,
    required this.controller,
    required this.onOpenBodyProgress,
  });

  final ProgressController controller;
  final VoidCallback onOpenBodyProgress;

  @override
  State<ProgressPage> createState() => _ProgressPageState();
}

class _ProgressPageState extends State<ProgressPage> {
  @override
  void initState() {
    super.initState();
    widget.controller.refresh();
  }

  Future<void> _openMeasurement([BodyMeasurement? measurement]) async {
    final input = await showModalBottomSheet<BodyMeasurementInput>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (_) => _MeasurementSheet(initial: measurement),
    );
    if (input == null) return;
    final saved = measurement == null
        ? await widget.controller.add(input)
        : await widget.controller.update(measurement, input);
    if (!mounted || !saved) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(measurement == null ? '身体数据已记录' : '身体数据已更新')),
    );
  }

  Future<void> _openNavyEstimator() async {
    final saved = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (_) => NavyBodyFatSheet(controller: widget.controller),
    );
    if (!mounted || saved != true) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(const SnackBar(content: Text('体脂估算已保存，可在趋势中查看')));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: ListenableBuilder(
          listenable: widget.controller,
          builder: (context, _) {
            final controller = widget.controller;
            SavedBodyFatEstimate? latestNavy;
            for (final estimate in controller.bodyFatEstimates) {
              if (estimate.method == 'navy') {
                latestNavy = estimate;
                break;
              }
            }
            return RefreshIndicator(
              onRefresh: controller.refresh,
              child: ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.fromLTRB(20, 22, 20, 34),
                children: [
                  AppPageHeader(
                    title: '进展',
                    subtitle: '看趋势，不被单次波动影响',
                    trailing: IconButton.filled(
                      tooltip: '记录身体数据',
                      onPressed: controller.submitting
                          ? null
                          : () => _openMeasurement(),
                      icon: const Icon(Icons.add_rounded),
                    ),
                  ),
                  const SizedBox(height: 18),
                  _RangeSelector(controller: controller),
                  if (controller.errorMessage case final message?) ...[
                    const SizedBox(height: 14),
                    AppErrorCard(message: message),
                  ],
                  const SizedBox(height: 18),
                  if (controller.loading && controller.overview == null)
                    const AppSurface(
                      child: SizedBox(
                        height: 180,
                        child: Center(child: CircularProgressIndicator()),
                      ),
                    )
                  else ...[
                    _BodyProgressEntry(
                      photoCountLabel: '照片记录与 AI 评估',
                      onTap: widget.onOpenBodyProgress,
                    ),
                    const SizedBox(height: 16),
                    _NavyEstimateCard(
                      latest: latestNavy,
                      onTap: _openNavyEstimator,
                    ),
                    const SizedBox(height: 16),
                    _TrainingSummaryCard(
                      summary: controller.overview?.training,
                      days: controller.selectedDays,
                    ),
                    const SizedBox(height: 26),
                    _TrendSection(controller: controller),
                    const SizedBox(height: 26),
                    _MeasurementSection(
                      measurements: controller.measurements,
                      onAdd: () => _openMeasurement(),
                      onEdit: _openMeasurement,
                    ),
                    if (controller.personalRecords.isNotEmpty) ...[
                      const SizedBox(height: 26),
                      _PersonalRecordSection(
                        records: controller.personalRecords,
                      ),
                    ],
                  ],
                ],
              ),
            );
          },
        ),
      ),
    );
  }
}

class _NavyEstimateCard extends StatelessWidget {
  const _NavyEstimateCard({required this.latest, required this.onTap});

  final SavedBodyFatEstimate? latest;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => AppSurface(
    onTap: onTap,
    padding: const EdgeInsets.all(16),
    child: Row(
      children: [
        const Icon(Icons.calculate_outlined, color: AppColors.indigo, size: 34),
        const SizedBox(width: 14),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('围度估算体脂', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 3),
              Text(
                latest == null
                    ? '输入身高、腰围、颈围等，由系统计算'
                    : '最近估算 ${latest!.result.valuePercent.toStringAsFixed(1)}% · 参考范围 ${latest!.result.rangeMinPercent.toStringAsFixed(1)}%–${latest!.result.rangeMaxPercent.toStringAsFixed(1)}%',
                style: Theme.of(context).textTheme.bodySmall
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

class _BodyProgressEntry extends StatelessWidget {
  const _BodyProgressEntry({
    required this.photoCountLabel,
    required this.onTap,
  });

  final String photoCountLabel;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return AppSurface(
      onTap: onTap,
      padding: const EdgeInsets.all(16),
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
              Icons.add_a_photo_outlined,
              color: AppColors.indigo,
            ),
          ),
          const SizedBox(width: 13),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('身体进度', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 3),
                Text(
                  photoCountLabel,
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

class _RangeSelector extends StatelessWidget {
  const _RangeSelector({required this.controller});

  final ProgressController controller;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        for (final days in const [30, 90, 180]) ...[
          ChoiceChip(
            label: Text(days == 180 ? '半年' : '$days 天'),
            selected: controller.selectedDays == days,
            onSelected: (_) => controller.selectRange(days),
          ),
          if (days != 180) const SizedBox(width: 8),
        ],
        const Spacer(),
        if (controller.loading)
          const SizedBox(
            width: 18,
            height: 18,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
      ],
    );
  }
}

class _TrainingSummaryCard extends StatelessWidget {
  const _TrainingSummaryCard({required this.summary, required this.days});

  final TrainingProgressSummary? summary;
  final int days;

  @override
  Widget build(BuildContext context) {
    final value = summary;
    return AppSurface(
      color: AppColors.darkCard,
      borderColor: AppColors.darkCard,
      padding: const EdgeInsets.fromLTRB(20, 20, 20, 18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const StatusPill(
                label: '训练概览',
                color: Color(0xFFFF7B89),
                icon: Icons.bolt_rounded,
              ),
              const Spacer(),
              Text(
                '近 $days 天',
                style: Theme.of(context).textTheme.labelMedium
                    ?.copyWith(color: Colors.white60),
              ),
            ],
          ),
          const SizedBox(height: 22),
          Row(
            children: [
              Expanded(
                child: _SummaryMetric(
                  value: '${value?.workoutCount ?? 0}',
                  label: '训练次数',
                ),
              ),
              const _VerticalLine(),
              Expanded(
                child: _SummaryMetric(
                  value: '${value?.totalDurationMinutes ?? 0}',
                  label: '训练分钟',
                ),
              ),
              const _VerticalLine(),
              Expanded(
                child: _SummaryMetric(
                  value: '${((value?.completionRate ?? 0) * 100).round()}%',
                  label: '计划完成',
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              const Icon(
                Icons.emoji_events_rounded,
                color: AppColors.amber,
                size: 19,
              ),
              const SizedBox(width: 8),
              Text(
                '${value?.personalRecordCount ?? 0} 项个人纪录',
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: Colors.white70,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _SummaryMetric extends StatelessWidget {
  const _SummaryMetric({required this.value, required this.label});

  final String value;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(
          value,
          style: Theme.of(context).textTheme.headlineMedium
              ?.copyWith(color: Colors.white),
        ),
        const SizedBox(height: 3),
        Text(
          label,
          style: Theme.of(context).textTheme.labelMedium
              ?.copyWith(color: Colors.white60),
        ),
      ],
    );
  }
}

class _VerticalLine extends StatelessWidget {
  const _VerticalLine();

  @override
  Widget build(BuildContext context) => Container(
    width: 1,
    height: 48,
    color: Colors.white.withValues(alpha: 0.13),
  );
}

class _TrendSection extends StatelessWidget {
  const _TrendSection({required this.controller});

  final ProgressController controller;

  @override
  Widget build(BuildContext context) {
    final metric = controller.selectedMetric;
    final points = controller.trend;
    final latest = points.isEmpty ? null : points.last.smoothedValue;
    final change = points.length < 2
        ? null
        : points.last.smoothedValue - points.first.smoothedValue;
    final color = _metricColor(metric);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SectionTitle(title: '身体趋势'),
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          children: [
            for (final item in BodyMetric.values)
              ChoiceChip(
                label: Text(item.label),
                selected: metric == item,
                onSelected: (_) => controller.selectMetric(item),
              ),
          ],
        ),
        if (metric == BodyMetric.bodyFat) ...[
          const SizedBox(height: 8),
          Text(
            '趋势可能包含设备实测与围度估算；方法不同，数值不宜直接比较。',
            style: Theme.of(context).textTheme.bodySmall
                ?.copyWith(color: AppColors.muted),
          ),
        ],
        const SizedBox(height: 12),
        AppSurface(
          padding: const EdgeInsets.fromLTRB(18, 18, 18, 16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '${metric.label}趋势',
                          style: Theme.of(context).textTheme.labelLarge,
                        ),
                        const SizedBox(height: 5),
                        Text.rich(
                          TextSpan(
                            text: latest?.toStringAsFixed(1) ?? '--',
                            style: Theme.of(context).textTheme.headlineMedium,
                            children: [
                              TextSpan(
                                text: ' ${metric.unit}',
                                style: Theme.of(context).textTheme.labelMedium,
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                  if (change != null)
                    StatusPill(
                      label:
                          '${change >= 0 ? '+' : ''}${change.toStringAsFixed(1)} ${metric.unit}',
                      color: color,
                      icon: change >= 0
                          ? Icons.trending_up_rounded
                          : Icons.trending_down_rounded,
                    ),
                ],
              ),
              const SizedBox(height: 18),
              if (controller.trendLoading)
                const SizedBox(
                  height: 176,
                  child: Center(child: CircularProgressIndicator()),
                )
              else if (points.isEmpty)
                Container(
                  height: 176,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    color: AppColors.canvas,
                    borderRadius: BorderRadius.circular(18),
                  ),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.show_chart_rounded, color: color, size: 32),
                      const SizedBox(height: 9),
                      Text(
                        '记录两次以上即可观察变化',
                        style: Theme.of(context).textTheme.bodyMedium
                            ?.copyWith(color: AppColors.muted),
                      ),
                    ],
                  ),
                )
              else ...[
                Semantics(
                  label:
                      '${metric.label}趋势，共 ${points.length} 个数据点，最新 ${latest?.toStringAsFixed(1)} ${metric.unit}',
                  child: SizedBox(
                    width: double.infinity,
                    height: 150,
                    child: CustomPaint(
                      painter: _TrendPainter(points: points, color: color),
                    ),
                  ),
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Text(
                      _shortDate(points.first.date),
                      style: Theme.of(context).textTheme.labelMedium,
                    ),
                    const Spacer(),
                    Text(
                      _shortDate(points.last.date),
                      style: Theme.of(context).textTheme.labelMedium,
                    ),
                  ],
                ),
              ],
            ],
          ),
        ),
      ],
    );
  }
}

class _TrendPainter extends CustomPainter {
  const _TrendPainter({required this.points, required this.color});

  final List<BodyTrendPoint> points;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    if (points.isEmpty) return;
    final values = points.map((point) => point.smoothedValue).toList();
    var minimum = values.reduce(math.min);
    var maximum = values.reduce(math.max);
    if ((maximum - minimum).abs() < 0.01) {
      minimum -= 1;
      maximum += 1;
    } else {
      final padding = (maximum - minimum) * 0.18;
      minimum -= padding;
      maximum += padding;
    }

    final gridPaint = Paint()
      ..color = AppColors.line
      ..strokeWidth = 1;
    for (var index = 0; index < 4; index++) {
      final y = size.height * index / 3;
      canvas.drawLine(Offset(0, y), Offset(size.width, y), gridPaint);
    }

    Offset offsetFor(int index) {
      final x = points.length == 1
          ? size.width / 2
          : size.width * index / (points.length - 1);
      final normalized =
          (points[index].smoothedValue - minimum) / (maximum - minimum);
      return Offset(x, size.height - normalized * size.height);
    }

    final path = Path();
    for (var index = 0; index < points.length; index++) {
      final offset = offsetFor(index);
      if (index == 0) {
        path.moveTo(offset.dx, offset.dy);
      } else {
        path.lineTo(offset.dx, offset.dy);
      }
    }
    canvas.drawPath(
      path,
      Paint()
        ..color = color
        ..strokeWidth = 3
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round
        ..style = PaintingStyle.stroke,
    );
    for (var index = 0; index < points.length; index++) {
      final offset = offsetFor(index);
      canvas.drawCircle(offset, 5, Paint()..color = Colors.white);
      canvas.drawCircle(offset, 3.3, Paint()..color = color);
    }
  }

  @override
  bool shouldRepaint(covariant _TrendPainter oldDelegate) =>
      oldDelegate.points != points || oldDelegate.color != color;
}

class _MeasurementSection extends StatelessWidget {
  const _MeasurementSection({
    required this.measurements,
    required this.onAdd,
    required this.onEdit,
  });

  final List<BodyMeasurement> measurements;
  final VoidCallback onAdd;
  final ValueChanged<BodyMeasurement> onEdit;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SectionTitle(
          title: '身体记录',
          action: TextButton.icon(
            onPressed: onAdd,
            icon: const Icon(Icons.add_rounded, size: 19),
            label: const Text('新增'),
          ),
        ),
        const SizedBox(height: 10),
        if (measurements.isEmpty)
          AppEmptyState(
            icon: Icons.monitor_weight_outlined,
            title: '从第一条记录开始',
            message: '可以只记录体重或围度；体脂可在上方用围度估算。',
            action: FilledButton.icon(
              onPressed: onAdd,
              icon: const Icon(Icons.add_rounded),
              label: const Text('记录身体数据'),
            ),
          )
        else
          ...measurements
              .take(10)
              .map(
                (measurement) => Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: _MeasurementTile(
                    measurement: measurement,
                    onTap: () => onEdit(measurement),
                  ),
                ),
              ),
      ],
    );
  }
}

class _MeasurementTile extends StatelessWidget {
  const _MeasurementTile({required this.measurement, required this.onTap});

  final BodyMeasurement measurement;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final values = <String>[
      if (measurement.weightKg case final value?)
        '${value.toStringAsFixed(1)} kg',
      if (measurement.waistCm case final value?)
        '腰围 ${value.toStringAsFixed(1)} cm',
      if (measurement.bodyFatPercent case final value?)
        '手填体脂 ${value.toStringAsFixed(1)}%',
      if (measurement.neckCm case final value?)
        '颈围 ${value.toStringAsFixed(1)} cm',
      if (measurement.hipCm case final value?)
        '臀围 ${value.toStringAsFixed(1)} cm',
    ];
    return AppSurface(
      onTap: onTap,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      child: Row(
        children: [
          Container(
            width: 48,
            height: 48,
            decoration: BoxDecoration(
              color: AppColors.primarySoft,
              borderRadius: BorderRadius.circular(16),
            ),
            child: const Icon(
              Icons.straighten_rounded,
              color: AppColors.primary,
              size: 23,
            ),
          ),
          const SizedBox(width: 13),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  values.join(' · '),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 4),
                Text(
                  _dateLabel(measurement.measuredAt),
                  style: Theme.of(context).textTheme.labelMedium,
                ),
                if (measurement.notes case final notes?
                    when notes.isNotEmpty) ...[
                  const SizedBox(height: 3),
                  Text(
                    notes,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.bodyMedium
                        ?.copyWith(color: AppColors.muted),
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(width: 8),
          const Icon(Icons.chevron_right_rounded, color: AppColors.muted),
        ],
      ),
    );
  }
}

class _PersonalRecordSection extends StatelessWidget {
  const _PersonalRecordSection({required this.records});

  final List<PersonalRecord> records;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SectionTitle(title: '个人纪录'),
        const SizedBox(height: 10),
        AppSurface(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
          child: Column(
            children: [
              for (
                var index = 0;
                index < math.min(records.length, 5);
                index++
              ) ...[
                _PersonalRecordTile(record: records[index]),
                if (index < math.min(records.length, 5) - 1)
                  const Divider(height: 1),
              ],
            ],
          ),
        ),
      ],
    );
  }
}

class _PersonalRecordTile extends StatelessWidget {
  const _PersonalRecordTile({required this.record});

  final PersonalRecord record;

  @override
  Widget build(BuildContext context) {
    final isWeight = record.recordType == 'max_weight';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 14),
      child: Row(
        children: [
          Container(
            width: 42,
            height: 42,
            decoration: BoxDecoration(
              color: AppColors.amberSoft,
              borderRadius: BorderRadius.circular(14),
            ),
            child: const Icon(
              Icons.emoji_events_rounded,
              color: AppColors.amber,
              size: 21,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  record.exerciseName,
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 3),
                Text(
                  '${isWeight ? '最大重量' : '最多次数'} · ${_dateLabel(record.occurredAt)}',
                  style: Theme.of(context).textTheme.labelMedium,
                ),
              ],
            ),
          ),
          Text(
            isWeight
                ? '${record.value.toStringAsFixed(1)} kg'
                : '${record.value.toStringAsFixed(0)} 次',
            style: Theme.of(context).textTheme.titleMedium
                ?.copyWith(color: AppColors.amber),
          ),
        ],
      ),
    );
  }
}

class _MeasurementSheet extends StatefulWidget {
  const _MeasurementSheet({this.initial});

  final BodyMeasurement? initial;

  @override
  State<_MeasurementSheet> createState() => _MeasurementSheetState();
}

class _MeasurementSheetState extends State<_MeasurementSheet> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _weight;
  late final TextEditingController _waist;
  late final TextEditingController _neck;
  late final TextEditingController _hip;
  late final TextEditingController _bodyFat;
  late final TextEditingController _conditions;
  late final TextEditingController _notes;
  late DateTime _date;
  String? _error;

  @override
  void initState() {
    super.initState();
    final initial = widget.initial;
    _weight = TextEditingController(text: _initialValue(initial?.weightKg));
    _waist = TextEditingController(text: _initialValue(initial?.waistCm));
    _neck = TextEditingController(text: _initialValue(initial?.neckCm));
    _hip = TextEditingController(text: _initialValue(initial?.hipCm));
    _bodyFat = TextEditingController(
      text: _initialValue(initial?.bodyFatPercent),
    );
    _conditions = TextEditingController(text: initial?.conditions ?? '');
    _notes = TextEditingController(text: initial?.notes ?? '');
    _date = initial?.measuredAt.toLocal() ?? DateTime.now();
  }

  @override
  void dispose() {
    for (final controller in [
      _weight,
      _waist,
      _neck,
      _hip,
      _bodyFat,
      _conditions,
      _notes,
    ]) {
      controller.dispose();
    }
    super.dispose();
  }

  String _initialValue(double? value) => value?.toStringAsFixed(1) ?? '';

  double? _value(TextEditingController controller) {
    final text = controller.text.trim();
    return text.isEmpty ? null : double.tryParse(text);
  }

  String? _text(TextEditingController controller) {
    final value = controller.text.trim();
    return value.isEmpty ? null : value;
  }

  Future<void> _pickDate() async {
    final value = await showDatePicker(
      context: context,
      initialDate: _date,
      firstDate: DateTime(2020),
      lastDate: DateTime.now(),
    );
    if (value != null) setState(() => _date = value);
  }

  void _submit() {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    final now = DateTime.now();
    final measuredAt = DateTime(
      _date.year,
      _date.month,
      _date.day,
      now.hour,
      now.minute,
    );
    final input = BodyMeasurementInput(
      measuredAt: measuredAt,
      weightKg: _value(_weight),
      waistCm: _value(_waist),
      neckCm: _value(_neck),
      hipCm: _value(_hip),
      bodyFatPercent: _value(_bodyFat),
      conditions: _text(_conditions),
      notes: _text(_notes),
    );
    if (!input.hasValue) {
      setState(() => _error = '请至少填写一项身体数据');
      return;
    }
    Navigator.pop(context, input);
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 4, 20, 24),
        child: Form(
          key: _formKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                widget.initial == null ? '记录身体数据' : '修改身体记录',
                style: Theme.of(context).textTheme.headlineSmall,
              ),
              const SizedBox(height: 6),
              Text(
                '可以只填写一项，同一时间和条件下记录更适合观察趋势。',
                style: Theme.of(context).textTheme.bodyMedium
                    ?.copyWith(color: AppColors.muted),
              ),
              const SizedBox(height: 18),
              OutlinedButton.icon(
                onPressed: _pickDate,
                icon: const Icon(Icons.calendar_today_rounded, size: 19),
                label: Text('测量日期：${_dateLabel(_date)}'),
              ),
              const SizedBox(height: 14),
              Row(
                children: [
                  Expanded(child: _measurementField(_weight, '体重（kg）', 500)),
                  const SizedBox(width: 10),
                  Expanded(child: _measurementField(_waist, '腰围（cm）', 400)),
                ],
              ),
              const SizedBox(height: 11),
              Row(
                children: [
                  Expanded(child: _measurementField(_hip, '臀围（cm）', 400)),
                  const SizedBox(width: 10),
                  Expanded(child: _measurementField(_neck, '颈围（cm）', 200)),
                ],
              ),
              const SizedBox(height: 11),
              ExpansionTile(
                title: const Text('有设备实测体脂？可选填'),
                tilePadding: EdgeInsets.zero,
                initiallyExpanded: widget.initial?.bodyFatPercent != null,
                children: [
                  _measurementField(_bodyFat, '设备实测体脂率（%）', 70),
                  const SizedBox(height: 8),
                  const Text('没有设备读数时无需填写；可在进展页通过围度估算。'),
                ],
              ),
              const SizedBox(height: 11),
              TextFormField(
                controller: _conditions,
                maxLength: 500,
                decoration: const InputDecoration(
                  labelText: '测量条件（可选）',
                  hintText: '例如：晨起空腹',
                  counterText: '',
                ),
              ),
              const SizedBox(height: 11),
              TextFormField(
                controller: _notes,
                minLines: 2,
                maxLines: 3,
                maxLength: 2000,
                decoration: const InputDecoration(
                  labelText: '备注（可选）',
                  hintText: '例如：本周睡眠较少',
                  counterText: '',
                ),
              ),
              if (_error case final message?) ...[
                const SizedBox(height: 9),
                Text(
                  message,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ],
              const SizedBox(height: 18),
              FilledButton(
                onPressed: _submit,
                child: Text(widget.initial == null ? '保存测量' : '保存修改'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  TextFormField _measurementField(
    TextEditingController controller,
    String label,
    double max,
  ) {
    return TextFormField(
      controller: controller,
      keyboardType: const TextInputType.numberWithOptions(decimal: true),
      inputFormatters: [
        FilteringTextInputFormatter.allow(RegExp(r'^\d*\.?\d{0,2}')),
      ],
      decoration: InputDecoration(labelText: label),
      validator: (text) {
        if (text == null || text.trim().isEmpty) return null;
        final value = double.tryParse(text);
        return value == null || value <= 0 || value > max ? '数值无效' : null;
      },
    );
  }
}

Color _metricColor(BodyMetric metric) => switch (metric) {
  BodyMetric.weight => AppColors.primary,
  BodyMetric.waist => AppColors.indigo,
  BodyMetric.bodyFat => AppColors.mint,
};

String _shortDate(DateTime raw) {
  final date = raw.toLocal();
  return '${date.month} 月 ${date.day} 日';
}

String _dateLabel(DateTime raw) {
  final date = raw.toLocal();
  return '${date.year} 年 ${date.month} 月 ${date.day} 日';
}
