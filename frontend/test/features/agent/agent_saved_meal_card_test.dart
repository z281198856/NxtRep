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
  testWidgets('saved food replacement shows the new food and estimate', (
    tester,
  ) async {
    final api = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('http://localhost/api/v1')),
      accessTokenProvider: () => null,
      httpClient: MockClient((_) async => throw StateError('unexpected write')),
    );
    final controller = AgentController(AgentRepository(api));
    addTearDown(controller.dispose);
    addTearDown(api.close);
    controller.messages = [
      AgentMessage(
        id: 'replacement',
        role: 'assistant',
        content: '请核对换菜草稿。',
        sequence: 1,
        createdAt: DateTime(2026, 10, 14),
      ),
    ];
    controller.confirmations = [
      AgentConfirmationCard.fromJson({
        'confirmation_id': 'replacement-card',
        'operation_type': 'nutrition_entry_update',
        'status': 'pending',
        'version': 1,
        'impact': '确认后替换原午饭中的食物',
        'after': {
          'preview': {
            'date': '2026-10-14',
            'meal_type': 'lunch',
            'eaten_at': '2026-10-14T12:00:00+08:00',
            'changes': [
              {
                'item_index': 1,
                'name': '虾仁滑蛋',
                'replacement_name': '炒空心菜',
                'old_amount_g': '150',
                'amount_g': '150',
                'estimate_assumptions': '按一小碗、少量油暂估',
              },
            ],
          },
        },
      }),
    ];
    await tester.pumpWidget(
      MaterialApp(home: AgentPage(controller: controller)),
    );
    await tester.pumpAndSettle();
    expect(find.text('虾仁滑蛋 → 炒空心菜（150 克）'), findsOneWidget);
    expect(find.textContaining('按一小碗、少量油暂估'), findsOneWidget);
    expect(find.text('替换项按新食物依据估算，其他食物保持原样'), findsOneWidget);
    expect(find.text('确认更正'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  for (final saved in [false, true]) {
    testWidgets(
      'nutrition reassessment explains its basis before approval ($saved)',
      (tester) async {
        var writes = 0;
        final api = ApiClient(
          config: ApiConfig(baseUri: Uri.parse('http://localhost/api/v1')),
          accessTokenProvider: () => null,
          httpClient: MockClient((_) async {
            writes++;
            throw StateError('unexpected write');
          }),
        );
        final controller = AgentController(AgentRepository(api));
        addTearDown(controller.dispose);
        addTearDown(api.close);
        controller.messages = [
          AgentMessage(
            id: 'reestimate',
            role: 'assistant',
            content: '根据少油做法重新估算，份量保持原样，请确认。',
            sequence: 1,
            createdAt: DateTime(2026, 10, 11),
          ),
        ];
        const assumption = '按非油炸做法和较少用油暂估，食材自身脂肪仍计入';
        controller.confirmations = [
          AgentConfirmationCard.fromJson({
            'confirmation_id': 'reestimate-card',
            'operation_type': saved
                ? 'nutrition_entry_update'
                : 'nutrition_entry_create',
            'status': 'pending',
            'version': 1,
            'impact': '确认后生效',
            'after': {
              'preview': saved
                  ? {
                      'date': '2026-10-11',
                      'eaten_at': '2026-10-11T12:00:00+08:00',
                      'meal_type': 'lunch',
                      'changes': [
                        {
                          'item_index': 0,
                          'name': '豆腐',
                          'old_amount_g': '200',
                          'amount_g': '200',
                          'nutrition_after': {'fat_g': '10'},
                          'estimate_assumptions': assumption,
                        },
                      ],
                      'totals_before': {
                        'kcal': '500',
                        'protein_g': '30',
                        'carbs_g': '40',
                        'fat_g': '30',
                      },
                      'totals_after': {
                        'kcal': '320',
                        'protein_g': '30',
                        'carbs_g': '40',
                        'fat_g': '10',
                      },
                    }
                  : {
                      'items': [
                        {
                          'name': '豆腐',
                          'amount_g': '200',
                          'source': 'model_estimated',
                          'estimate_assumptions': assumption,
                        },
                      ],
                      'totals': {
                        'kcal': '320',
                        'protein_g': '30',
                        'carbs_g': '40',
                        'fat_g': '10',
                      },
                    },
            },
          }),
        ];
        await tester.pumpWidget(
          MaterialApp(home: AgentPage(controller: controller)),
        );
        await tester.pumpAndSettle();
        expect(find.textContaining(assumption), findsOneWidget);
        expect(
          find.text(saved ? '豆腐：200 克 → 200 克' : '豆腐 200 克（暂定估算）'),
          findsOneWidget,
        );
        expect(
          find.text(saved ? '脂肪：30 → 10 克' : '碳水 40 克 · 脂肪 10 克'),
          findsOneWidget,
        );
        if (saved) {
          expect(find.text('所列食物采用新的暂定估算，其他食物保持原样'), findsOneWidget);
          expect(find.text('沿用原营养依据，其他食物保持原样'), findsNothing);
        }
        expect(writes, 0);
        expect(tester.takeException(), isNull);
      },
    );
  }

  testWidgets(
    'single food removal previews the selected food before approval',
    (tester) async {
      var writes = 0;
      final api = ApiClient(
        config: ApiConfig(baseUri: Uri.parse('http://localhost/api/v1')),
        accessTokenProvider: () => null,
        httpClient: MockClient((_) async {
          writes++;
          throw StateError('unexpected write before approval');
        }),
      );
      final controller = AgentController(AgentRepository(api));
      addTearDown(controller.dispose);
      addTearDown(api.close);
      controller.messages = [
        AgentMessage(
          id: 'reply',
          role: 'assistant',
          content: '请核对移除食物的草稿。',
          sequence: 1,
          createdAt: DateTime(2026, 10, 8),
        ),
      ];
      controller.confirmations = const [
        AgentConfirmationCard(
          id: 'remove-food',
          operationType: 'nutrition_entry_update',
          status: 'pending',
          impact: '确认后仅移除鸡蛋，保留这餐其他食物。',
          version: 1,
          after: {
            'preview': {
              'date': '2026-10-08',
              'eaten_at': '2026-10-08T12:00:00+08:00',
              'meal_type': 'lunch',
              'changes': [],
              'removed_items': [
                {'item_index': 1, 'name': '鸡蛋', 'amount_g': '100'},
              ],
              'totals_before': {
                'kcal': '410',
                'protein_g': '19',
                'carbs_g': '57',
                'fat_g': '12',
              },
              'totals_after': {
                'kcal': '260',
                'protein_g': '6',
                'carbs_g': '56',
                'fat_g': '2',
              },
            },
          },
        ),
      ];
      await tester.pumpWidget(
        MaterialApp(home: AgentPage(controller: controller)),
      );
      await tester.pumpAndSettle();
      expect(find.text('移除 鸡蛋（100 克），保留这餐其他食物'), findsOneWidget);
      expect(find.text('这餐热量：410 → 260 千卡'), findsOneWidget);
      expect(find.text('确认更正'), findsOneWidget);
      expect(find.text('确认删除'), findsNothing);
      expect(find.text('删除饮食记录'), findsNothing);
      expect(writes, 0);
      expect(tester.takeException(), isNull);
    },
  );

  for (final delete in [false, true]) {
    testWidgets(
      'saved meal card previews ${delete ? 'delete' : 'portion correction'}',
      (tester) async {
        final api = ApiClient(
          config: ApiConfig(baseUri: Uri.parse('http://localhost/api/v1')),
          accessTokenProvider: () => null,
          httpClient: MockClient(
            (_) async => throw StateError('unexpected write'),
          ),
        );
        final controller = AgentController(AgentRepository(api));
        addTearDown(controller.dispose);
        addTearDown(api.close);
        controller.messages = [
          AgentMessage(
            id: 'reply',
            role: 'assistant',
            content: '请核对这餐草稿。',
            sequence: 1,
            createdAt: DateTime(2026),
          ),
        ];
        controller.confirmations = [
          AgentConfirmationCard.fromJson({
            'confirmation_id': 'saved-meal',
            'operation_type': delete
                ? 'nutrition_entry_delete'
                : 'nutrition_entry_update',
            'status': 'pending',
            'version': 1,
            'impact': '原记录和修订保留',
            'after': {
              'preview': {
                'date': '2026-10-07',
                'eaten_at': '2026-10-07T12:00:00+08:00',
                'meal_type': 'lunch',
                if (!delete)
                  'changes': [
                    {'name': '熟米饭', 'old_amount_g': '200', 'amount_g': '100'},
                  ],
                'totals_before': {
                  'kcal': '410',
                  'protein_g': '19',
                  'carbs_g': '57',
                  'fat_g': '12',
                },
                'totals_after': delete
                    ? {
                        'kcal': '0',
                        'protein_g': '0',
                        'carbs_g': '0',
                        'fat_g': '0',
                      }
                    : {
                        'kcal': '280',
                        'protein_g': '16',
                        'carbs_g': '29',
                        'fat_g': '11',
                      },
              },
            },
          }),
        ];
        await tester.pumpWidget(
          MaterialApp(home: AgentPage(controller: controller)),
        );
        await tester.pumpAndSettle();
        expect(find.text(delete ? '删除饮食记录' : '更正已保存饮食'), findsOneWidget);
        expect(find.text(delete ? '确认删除' : '确认更正'), findsOneWidget);
        expect(find.text('2026-10-07 · 午餐 · 12:00'), findsOneWidget);
        expect(
          find.text('熟米饭：200 克 → 100 克'),
          delete ? findsNothing : findsOneWidget,
        );
        expect(
          find.text('这餐热量：410 → ${delete ? '0' : '280'} 千卡'),
          findsOneWidget,
        );
        expect(
          find.text('沿用原营养依据，其他食物保持原样'),
          delete ? findsNothing : findsOneWidget,
        );
        expect(
          find.text('确认后仅将这一餐从统计中移除，原记录和修订保留'),
          delete ? findsOneWidget : findsNothing,
        );
        expect(find.text('调整份量'), findsNothing);
        expect(tester.takeException(), isNull);
      },
    );
  }
}
