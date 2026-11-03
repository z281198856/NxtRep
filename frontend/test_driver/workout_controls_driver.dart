import 'dart:io';

import 'package:integration_test/integration_test_driver_extended.dart';

Future<void> main() async {
  await integrationDriver(
    onScreenshot: (name, bytes, [args]) async {
      final directory = Directory('../.local');
      await directory.create(recursive: true);
      await File('${directory.path}/workout-controls-$name.png')
          .writeAsBytes(bytes);
      return true;
    },
  );
}
