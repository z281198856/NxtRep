import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/agent/data/agent_repository.dart';
import 'package:nxtrep/features/agent/domain/agent_models.dart';
import 'package:nxtrep/features/agent/presentation/agent_controller.dart';
import 'package:nxtrep/features/agent/presentation/agent_page.dart';

void main() {
  testWidgets('renders an incomplete streamed bullet without throwing', (
    tester,
  ) async {
    final apiClient = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('http://localhost/api/v1')),
      accessTokenProvider: () => null,
      httpClient: MockClient((_) async => throw StateError('unexpected call')),
    );
    final controller = AgentController(AgentRepository(apiClient));
    controller.messages = [
      AgentMessage(
        id: 'assistant-message',
        role: 'assistant',
        content: '- ',
        sequence: 1,
        createdAt: DateTime(2026, 9, 19),
        pending: true,
      ),
    ];
    addTearDown(controller.dispose);
    addTearDown(apiClient.close);

    await tester.pumpWidget(
      MaterialApp(home: AgentPage(controller: controller)),
    );
    await tester.pump();

    expect(tester.takeException(), isNull);
  });

  testWidgets('shows only answer and analysis sections for a concise reply', (
    tester,
  ) async {
    final apiClient = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('http://localhost/api/v1')),
      accessTokenProvider: () => null,
      httpClient: MockClient((_) async => throw StateError('unexpected call')),
    );
    final controller = AgentController(AgentRepository(apiClient));
    controller.messages = [
      AgentMessage(
        id: 'assistant-message',
        role: 'assistant',
        content: '回答：今天练全身 A。\n分析：依据你的每周三练安排。',
        sequence: 1,
        createdAt: DateTime(2026, 9, 19),
      ),
    ];
    addTearDown(controller.dispose);
    addTearDown(apiClient.close);

    await tester.pumpWidget(
      MaterialApp(home: AgentPage(controller: controller)),
    );

    expect(find.text('回答'), findsOneWidget);
    expect(find.text('分析'), findsOneWidget);
    expect(find.text('今天练全身 A。'), findsOneWidget);
    expect(find.text('依据你的每周三练安排。'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('confirmation card previews a plan without technical IDs', (
    tester,
  ) async {
    final apiClient = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('http://localhost/api/v1')),
      accessTokenProvider: () => null,
      httpClient: MockClient((_) async => throw StateError('unexpected call')),
    );
    final controller = AgentController(AgentRepository(apiClient));
    controller.messages = [
      AgentMessage(
        id: 'assistant-message',
        role: 'assistant',
        content: '回答：训练计划草稿已生成。\n分析：每周训练三次。',
        sequence: 1,
        createdAt: DateTime(2026, 9, 19),
      ),
    ];
    controller.confirmations = const [
      AgentConfirmationCard(
        id: 'private-technical-id',
        operationType: 'training_plan_activate',
        status: 'pending',
        impact: '未来日历使用新计划，历史训练不变',
        version: 1,
        draft: {
          'name': '三日全身计划',
          'weekly_frequency': 3,
          'days': [
            {
              'name': '全身 A',
              'estimated_minutes': 45,
              'exercises': [
                {
                  'exercise_name': '哑铃卧推',
                  'target_sets': 3,
                  'rep_min': 8,
                  'rep_max': 10,
                  'target_rir': 2,
                },
              ],
            },
            {'name': '全身 B'},
            {'name': '全身 C'},
          ],
        },
      ),
    ];
    addTearDown(controller.dispose);
    addTearDown(apiClient.close);

    await tester.pumpWidget(
      MaterialApp(home: AgentPage(controller: controller)),
    );
    await tester.ensureVisible(find.text('三日全身计划'));

    expect(find.text('启用训练计划'), findsOneWidget);
    expect(find.text('三日全身计划'), findsOneWidget);
    expect(find.text('每周 3 次'), findsOneWidget);
    expect(find.text('训练日：全身 A · 全身 B · 全身 C'), findsOneWidget);
    expect(find.text('确认启用'), findsOneWidget);
    await tester.tap(find.text('查看各训练日和动作'));
    await tester.pumpAndSettle();
    expect(find.textContaining('哑铃卧推'), findsOneWidget);
    expect(find.textContaining('3 组 × 8–10 次'), findsOneWidget);
    expect(find.text('private-technical-id'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
