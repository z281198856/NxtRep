import 'package:flutter/material.dart';

import '../../../core/network/api_exception.dart';
import '../../../core/widgets/app_widgets.dart';
import '../domain/training_models.dart';
import 'active_plan_detail_page.dart';
import 'plan_controller.dart';

class CalendarEventDetailPage extends StatefulWidget {
  const CalendarEventDetailPage({
    super.key,
    required this.controller,
    required this.eventId,
  });

  final PlanController controller;
  final String eventId;

  @override
  State<CalendarEventDetailPage> createState() =>
      _CalendarEventDetailPageState();
}

class _CalendarEventDetailPageState extends State<CalendarEventDetailPage> {
  late Future<CalendarEventDetail> _detail;

  @override
  void initState() {
    super.initState();
    _detail = widget.controller.getCalendarEvent(widget.eventId);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('当天训练安排')),
    body: FutureBuilder<CalendarEventDetail>(
      future: _detail,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          final error = snapshot.error;
          return ListView(
            padding: const EdgeInsets.all(20),
            children: [
              AppErrorCard(
                message: error is ApiException
                    ? error.message
                    : '训练安排详情加载失败，请重试。',
              ),
              TextButton.icon(
                onPressed: () => setState(() {
                  _detail = widget.controller.getCalendarEvent(widget.eventId);
                }),
                icon: const Icon(Icons.refresh_rounded),
                label: const Text('重新加载'),
              ),
            ],
          );
        }
        final detail = snapshot.requireData;
        final event = detail.event;
        final date = event.scheduledDate;
        final exercises = detail.exercises;
        final status = switch (event.status) {
          'completed' => '已完成',
          'missed' => '未完成',
          'skipped' => '已跳过',
          _ => '待训练',
        };
        return ListView(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 32),
          children: [
            Text(event.title, style: Theme.of(context).textTheme.headlineSmall),
            const SizedBox(height: 8),
            Text(
              '${date.year}年${date.month}月${date.day}日 · $status · 约 ${event.estimatedMinutes} 分钟',
            ),
            const SizedBox(height: 20),
            if (exercises.isEmpty)
              const AppEmptyState(
                icon: Icons.fitness_center_rounded,
                title: '这项安排没有保存动作明细',
                message: '这里只展示该日历安排已保存的内容。',
              )
            else
              AppSurface(
                child: Column(
                  children: [
                    for (var index = 0; index < exercises.length; index++)
                      PlanExerciseRow(
                        number: index + 1,
                        exercise: exercises[index],
                      ),
                  ],
                ),
              ),
          ],
        );
      },
    ),
  );
}
