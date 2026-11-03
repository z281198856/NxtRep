import 'package:flutter/material.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../domain/training_models.dart';

class TrainingMonthCalendar extends StatelessWidget {
  const TrainingMonthCalendar({
    super.key,
    required this.month,
    required this.selectedDate,
    required this.events,
    required this.loading,
    required this.onSelected,
    required this.onMonthChanged,
  });

  final DateTime month;
  final DateTime selectedDate;
  final List<CalendarEvent> events;
  final bool loading;
  final ValueChanged<DateTime> onSelected;
  final ValueChanged<DateTime> onMonthChanged;

  @override
  Widget build(BuildContext context) {
    final first = DateTime(month.year, month.month);
    final days = DateTime(month.year, month.month + 1, 0).day;
    final offset = first.weekday - 1;
    final cells = ((offset + days) / 7).ceil() * 7;
    final today = DateUtils.dateOnly(DateTime.now());
    return AppSurface(
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(
                Icons.calendar_month_rounded,
                size: 20,
                color: AppColors.primary,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  '训练日历',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ),
              TextButton(
                onPressed: loading ? null : () => onMonthChanged(today),
                child: const Text('今天'),
              ),
            ],
          ),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              IconButton(
                tooltip: '上个月',
                onPressed: loading
                    ? null
                    : () =>
                          onMonthChanged(DateTime(month.year, month.month - 1)),
                icon: const Icon(Icons.chevron_left_rounded),
              ),
              Text(
                '${month.year} 年 ${month.month} 月',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              IconButton(
                tooltip: '下个月',
                onPressed: loading
                    ? null
                    : () =>
                          onMonthChanged(DateTime(month.year, month.month + 1)),
                icon: const Icon(Icons.chevron_right_rounded),
              ),
            ],
          ),
          Row(
            children: [
              for (final label in const ['一', '二', '三', '四', '五', '六', '日'])
                Expanded(
                  child: Center(
                    child: Text(
                      label,
                      style: const TextStyle(
                        fontSize: 12,
                        color: AppColors.muted,
                      ),
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 8),
          GridView.builder(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            itemCount: cells,
            gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
              crossAxisCount: 7,
              mainAxisSpacing: 4,
              crossAxisSpacing: 4,
              mainAxisExtent: 48,
            ),
            itemBuilder: (context, index) {
              final number = index - offset + 1;
              if (number < 1 || number > days) return const SizedBox.shrink();
              final date = DateTime(month.year, month.month, number);
              final scheduled = events
                  .where(
                    (event) => DateUtils.isSameDay(event.scheduledDate, date),
                  )
                  .toList();
              final selected = DateUtils.isSameDay(selectedDate, date);
              final color = scheduled.any((event) => event.status == 'planned')
                  ? AppColors.primary
                  : scheduled.any((event) => event.status == 'missed')
                  ? AppColors.amber
                  : scheduled.any((event) => event.status == 'completed')
                  ? AppColors.mint
                  : AppColors.muted;
              return Semantics(
                button: true,
                selected: selected,
                label:
                    '${date.year}年${date.month}月${date.day}日${scheduled.isEmpty ? '' : '，${scheduled.length}项训练安排'}',
                child: InkWell(
                  key: ValueKey(
                    'calendar-day-${date.year}-${date.month}-${date.day}',
                  ),
                  onTap: loading ? null : () => onSelected(date),
                  borderRadius: BorderRadius.circular(12),
                  child: Container(
                    decoration: BoxDecoration(
                      color: selected ? AppColors.primarySoft : null,
                      borderRadius: BorderRadius.circular(12),
                      border: DateUtils.isSameDay(date, today)
                          ? Border.all(color: AppColors.primary)
                          : null,
                    ),
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Text(
                          '$number',
                          style: TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w600,
                            color: selected ? AppColors.primary : AppColors.ink,
                          ),
                        ),
                        const SizedBox(height: 3),
                        Container(
                          key: ValueKey(
                            'calendar-marker-${date.year}-${date.month}-${date.day}',
                          ),
                          width: 4,
                          height: 4,
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            color: scheduled.isEmpty
                                ? Colors.transparent
                                : color,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              );
            },
          ),
          const SizedBox(height: 8),
          const Wrap(
            spacing: 12,
            runSpacing: 4,
            children: [
              _CalendarLegend('待训练', AppColors.primary),
              _CalendarLegend('已完成', AppColors.mint),
              _CalendarLegend('未完成', AppColors.amber),
              _CalendarLegend('已跳过', AppColors.muted),
            ],
          ),
        ],
      ),
    );
  }
}

class _CalendarLegend extends StatelessWidget {
  const _CalendarLegend(this.label, this.color);
  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Icon(Icons.circle, size: 5, color: color),
      const SizedBox(width: 4),
      Text(label, style: const TextStyle(fontSize: 11, color: AppColors.muted)),
    ],
  );
}
