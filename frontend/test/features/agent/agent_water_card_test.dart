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
  for (final saved in [false, true]) {
    testWidgets('water card shows amount and Shanghai day; saved=$saved', (
      tester,
    ) async {
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
          content: '请核对饮水量。',
          sequence: 1,
          createdAt: DateTime(2026),
        ),
      ];
      controller.confirmations = [
        AgentConfirmationCard.fromJson({
          'confirmation_id': 'water',
          'operation_type': 'water_entry_create',
          'status': saved ? 'succeeded' : 'pending',
          'version': saved ? 2 : 1,
          'impact': '确认后计入当天饮水',
          'after': {
            'water': {'amount_ml': 500, 'consumed_at': '2026-10-23T16:30:00Z'},
          },
        }),
      ];
      await tester.pumpWidget(
        MaterialApp(home: AgentPage(controller: controller)),
      );
      await tester.pumpAndSettle();
      expect(find.text(saved ? '饮水记录' : '保存饮水记录'), findsOneWidget);
      expect(find.text('饮水 500 ml'), findsOneWidget);
      expect(find.text('2026年10月24日'), findsOneWidget);
      expect(find.text('确认保存'), saved ? findsNothing : findsOneWidget);
      expect(find.text('训练记录'), findsNothing);
      expect(tester.takeException(), isNull);
    });
  }
}
