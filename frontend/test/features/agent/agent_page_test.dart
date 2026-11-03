import 'dart:convert';

import 'package:http/http.dart' as http;
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
  testWidgets('custom food shows basis and estimate before catalog approval', (
    tester,
  ) async {
    final api = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('http://localhost/api/v1')),
      accessTokenProvider: () => null,
      httpClient: MockClient((_) async => throw StateError('unexpected call')),
    );
    final controller = AgentController(AgentRepository(api));
    addTearDown(controller.dispose);
    addTearDown(api.close);
    controller.messages = [
      AgentMessage(
        id: 'reply',
        role: 'assistant',
        content: '食品草稿待确认。',
        sequence: 1,
        createdAt: DateTime(2026),
      ),
    ];
    controller.confirmations = const [
      AgentConfirmationCard(
        id: 'food-draft',
        operationType: 'food_create',
        status: 'pending',
        impact: '确认后进入食品库，不计入饮食记录',
        version: 1,
        after: {
          'food': {
            'name': '自制燕麦饼',
            'basis_amount_g': '100',
            'kcal': '300',
            'protein_g': '10',
            'carbs_g': '40',
            'fat_g': '11',
            'source': 'model_estimated',
            'confidence': 'low',
            'notes': '按常见配方估算，请核对',
          },
        },
      ),
    ];
    await tester.pumpWidget(
      MaterialApp(home: AgentPage(controller: controller)),
    );
    await tester.pumpAndSettle();
    expect(find.text('添加自定义食品'), findsOneWidget);
    expect(find.text('自制燕麦饼'), findsOneWidget);
    expect(find.text('每 100 克：300 千卡'), findsOneWidget);
    expect(find.text('暂定估算，确认前请核对份量和营养'), findsOneWidget);
    expect(find.text('确认添加'), findsOneWidget);
    expect(find.text('调整份量'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'editing pending meal replaces old card and displays recalculated total',
    (tester) async {
      final requests = <Map<String, dynamic>>[];
      final api = ApiClient(
        config: ApiConfig(baseUri: Uri.parse('http://localhost/api/v1')),
        accessTokenProvider: () => null,
        httpClient: MockClient((request) async {
          expect(
            request.url.path,
            '/api/v1/nutrition/pending-entries/old/portions',
          );
          requests.add(jsonDecode(request.body) as Map<String, dynamic>);
          return http.Response(
            jsonEncode({
              'confirmation_id': 'new',
              'operation_type': 'nutrition_entry_create',
              'status': 'pending',
              'impact': '确认后保存',
              'version': 1,
              'after': {
                'entry': {'meal_type': 'lunch'},
                'preview': {
                  'items': [
                    {'name': '米饭', 'amount_g': '100'},
                  ],
                  'totals': {
                    'kcal': '116',
                    'protein_g': '3',
                    'carbs_g': '26',
                    'fat_g': '1',
                  },
                },
              },
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }),
      );
      final controller = AgentController(AgentRepository(api));
      addTearDown(controller.dispose);
      addTearDown(api.close);
      controller.messages = [
        AgentMessage(
          id: 'a',
          role: 'assistant',
          content: '草稿',
          sequence: 1,
          createdAt: DateTime(2026),
        ),
      ];
      controller.confirmations = const [
        AgentConfirmationCard(
          id: 'old',
          operationType: 'nutrition_entry_create',
          status: 'pending',
          impact: '待确认',
          version: 2,
          after: {
            'entry': {'meal_type': 'lunch'},
            'preview': {
              'items': [
                {'name': '米饭', 'amount_g': '200'},
              ],
              'totals': {
                'kcal': '232',
                'protein_g': '6',
                'carbs_g': '52',
                'fat_g': '2',
              },
            },
          },
        ),
      ];
      await tester.pumpWidget(
        MaterialApp(home: AgentPage(controller: controller)),
      );
      await tester.ensureVisible(find.text('调整份量'));
      await tester.tap(find.text('调整份量'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextFormField), '100');
      await tester.tap(find.text('重新计算草稿'));
      // Wall time can advance while a slow exit animation still owns the fields.
      // The controls must remain alive until the route is actually removed.
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 300)),
      );
      await tester.pumpAndSettle();
      expect(requests.single['expected_version'], 2);
      expect(
        (requests.single['changes'] as List).single['amount_g'],
        '100.000',
      );
      expect(controller.confirmations.single.id, 'new');
      expect(find.textContaining('116', findRichText: true), findsWidgets);
      expect(find.text('确认保存'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  for (final operation in [
    'calendar_reschedule',
    'training_progression_apply',
  ]) {
    testWidgets('$operation previews exact changes and warnings', (
      tester,
    ) async {
      final api = ApiClient(
        config: ApiConfig(baseUri: Uri.parse('http://localhost/api/v1')),
        accessTokenProvider: () => null,
        httpClient: MockClient(
          (_) async => throw StateError('unexpected call'),
        ),
      );
      final controller = AgentController(AgentRepository(api));
      controller.messages = [
        AgentMessage(
          id: 'reply',
          role: 'assistant',
          content: '草稿待确认。',
          sequence: 1,
          createdAt: DateTime(2026, 10, 5),
        ),
      ];
      controller.confirmations = [
        AgentConfirmationCard(
          id: 'internal-draft-id',
          operationType: operation,
          status: 'pending',
          impact: '确认后才生效',
          version: 1,
          draft: operation == 'calendar_reschedule'
              ? {
                  'before_events': [
                    {'scheduled_date': '2026-10-07', 'title': '训练B'},
                  ],
                  'after_events': [
                    {'scheduled_date': '2026-10-08', 'title': '训练B'},
                  ],
                }
              : {
                  'suggestions': [
                    {
                      'exercise_name': '哑铃深蹲',
                      'current_target': {'weight_kg': '50'},
                      'proposed_target': {'weight_kg': '50'},
                      'evidence': ['本次完成 3 组'],
                      'warnings': ['本次记录了疼痛，暂停加重并优先评估疼痛'],
                    },
                  ],
                },
        ),
      ];
      addTearDown(controller.dispose);
      addTearDown(api.close);
      await tester.pumpWidget(
        MaterialApp(home: AgentPage(controller: controller)),
      );
      if (operation == 'calendar_reschedule') {
        expect(find.text('原安排：2026-10-07 训练B'), findsOneWidget);
        expect(find.text('拟安排：2026-10-08 训练B'), findsOneWidget);
      } else {
        expect(find.text('哑铃深蹲：50 → 50 公斤'), findsOneWidget);
        expect(find.textContaining('暂停加重'), findsOneWidget);
      }
      expect(find.text('确认更改'), findsOneWidget);
      expect(find.text('internal-draft-id'), findsNothing);
      expect(tester.takeException(), isNull);
    });
  }
  testWidgets('meal confirmation shows real items and estimate assumptions', (
    tester,
  ) async {
    final api = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('http://localhost/api/v1')),
      accessTokenProvider: () => null,
      httpClient: MockClient((_) async => throw StateError('unexpected call')),
    );
    final controller = AgentController(AgentRepository(api));
    controller.messages = [
      AgentMessage(
        id: 'reply',
        role: 'assistant',
        content: '草稿待确认。',
        sequence: 1,
        createdAt: DateTime(2026, 10, 5),
      ),
    ];
    controller.confirmations = const [
      AgentConfirmationCard(
        id: 'private-meal-id',
        operationType: 'nutrition_entry_create',
        status: 'pending',
        impact: '确认后才纳入统计',
        version: 1,
        after: {
          'entry': {'meal_type': 'lunch'},
        },
        draft: {
          'items': [
            {'name': '鸡蛋', 'amount_g': '100', 'source': 'model_estimated'},
            {'name': '米饭', 'amount_g': '150', 'source': 'usda'},
          ],
          'totals': {'kcal': '340', 'protein_g': '17'},
          'notes': '鸡蛋暂按两颗可食部100克，米饭一碗150克。',
        },
      ),
    ];
    addTearDown(controller.dispose);
    addTearDown(api.close);
    await tester.pumpWidget(
      MaterialApp(home: AgentPage(controller: controller)),
    );
    expect(find.text('鸡蛋 100 克（暂定估算）'), findsOneWidget);
    expect(find.text('米饭 150 克'), findsOneWidget);
    expect(find.textContaining('合计约 340 千卡'), findsOneWidget);
    expect(find.text('确认保存'), findsOneWidget);
    expect(find.text('private-meal-id'), findsNothing);
    expect(tester.takeException(), isNull);
  });
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

  testWidgets('integrates legacy analysis into reply without fixed headings', (
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

    expect(find.text('回答'), findsNothing);
    expect(find.text('分析'), findsNothing);
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
