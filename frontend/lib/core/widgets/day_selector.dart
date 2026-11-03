import 'package:flutter/material.dart';

class DaySelector extends StatelessWidget {
  const DaySelector({
    super.key,
    required this.date,
    required this.onSelected,
    this.enabled = true,
  });

  final DateTime date;
  final ValueChanged<DateTime> onSelected;
  final bool enabled;

  Future<void> _pickDate(BuildContext context) async {
    final selected = await showDatePicker(
      context: context,
      initialDate: date,
      firstDate: DateTime(1970),
      lastDate: DateTime(2100, 12, 31),
      helpText: '选择要查看的日期',
      cancelText: '取消',
      confirmText: '确定',
      fieldLabelText: '日期',
      errorFormatText: '日期格式不正确',
      errorInvalidText: '请选择有效日期',
    );
    if (selected != null) onSelected(selected);
  }

  @override
  Widget build(BuildContext context) {
    final today = DateUtils.dateOnly(DateTime.now());
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            IconButton(
              tooltip: '前一天',
              onPressed: enabled && date.isAfter(DateTime(1970))
                  ? () => onSelected(
                      DateTime(date.year, date.month, date.day - 1),
                    )
                  : null,
              icon: const Icon(Icons.chevron_left_rounded),
            ),
            Expanded(
              child: OutlinedButton.icon(
                key: const ValueKey('day-selector-calendar'),
                onPressed: enabled ? () => _pickDate(context) : null,
                icon: const Icon(Icons.calendar_month_rounded, size: 20),
                label: Text('${date.year}年${date.month}月${date.day}日'),
              ),
            ),
            IconButton(
              tooltip: '后一天',
              onPressed: enabled && date.isBefore(DateTime(2100, 12, 31))
                  ? () => onSelected(
                      DateTime(date.year, date.month, date.day + 1),
                    )
                  : null,
              icon: const Icon(Icons.chevron_right_rounded),
            ),
          ],
        ),
        if (!DateUtils.isSameDay(date, today))
          Align(
            alignment: Alignment.centerRight,
            child: TextButton(
              onPressed: enabled ? () => onSelected(today) : null,
              child: const Text('返回今天'),
            ),
          ),
      ],
    );
  }
}
