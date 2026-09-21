import 'package:flutter_test/flutter_test.dart';
import 'package:nxtrep/core/network/sse_event.dart';

void main() {
  test(
    'parses ids, event names, multiline data and heartbeat comments',
    () async {
      final events = await parseSseLines(
        Stream.fromIterable([
          ': heartbeat',
          '',
          'id: 42',
          'event: chunk',
          'data: first',
          'data: second',
          '',
          'event: completed',
          'data: {"status":"completed"}',
          '',
        ]),
      ).toList();

      expect(events, hasLength(2));
      expect(events.first.id, '42');
      expect(events.first.event, 'chunk');
      expect(events.first.data, 'first\nsecond');
      expect(events.last.isTerminal, isTrue);
    },
  );
}
