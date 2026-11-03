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
  testWidgets('date correction previews exact meals without changing data', (
    tester,
  ) async {
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
        id: 'date-message',
        role: 'assistant',
        content: '请核对日期和餐食后确认。',
        sequence: 1,
        createdAt: DateTime(2026, 10, 12),
      ),
    ];
    controller.confirmations = [
      AgentConfirmationCard.fromJson({
        'confirmation_id': 'internal-date-card-id',
        'operation_type': 'nutrition_entries_date_change',
        'status': 'pending',
        'version': 1,
        'impact': '确认后更新两天统计',
        'after': {
          'preview': {
            'source_date': '2026-10-11',
            'target_date': '2026-10-10',
            'entries': [
              {
                'meal_type': 'lunch',
                'time': '12:00',
                'foods': ['米饭', '鸡胸肉'],
                'kcal': '599',
              },
              {
                'meal_type': 'dinner',
                'time': '18:00',
                'foods': ['牛肉'],
                'kcal': '775',
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
    expect(find.text('更正饮食日期'), findsOneWidget);
    expect(find.text('日期：2026-10-11 → 2026-10-10'), findsOneWidget);
    expect(find.text('12:00 · 午餐 · 米饭、鸡胸肉 · 599 千卡'), findsOneWidget);
    expect(find.text('18:00 · 晚餐 · 牛肉 · 775 千卡'), findsOneWidget);
    expect(find.text('确认改日期'), findsOneWidget);
    expect(find.textContaining('internal-date-card-id'), findsNothing);
    expect(writes, 0);
    expect(tester.takeException(), isNull);
  });
}
