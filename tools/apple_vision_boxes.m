// Where text and faces are in an image, on this machine, with Apple Vision.
//
// The film publishes real footage of public roads, so two things have to be
// found before it can be published: number plates, which are blurred, and
// faces, whose windows are dropped (the owner's rule, 2026-09-08). Both are
// found here, on device, from local files. Nothing is uploaded and no string
// is interpreted: this prints where the boxes are and what the text says, and
// the caller decides which of them is a plate.
//
// Boxes are Vision's own normalised coordinates, with the origin at the
// BOTTOM left of the image. A caller drawing on video has to flip y.
//
// Usage: apple_vision_boxes <image> [<image> ...]   -> JSON array, one per image.

#import <Foundation/Foundation.h>
#import <Vision/Vision.h>

static void Fail(NSString *message) {
  fprintf(stderr, "%s\n", message.UTF8String);
  exit(1);
}

static NSDictionary *BoxOf(CGRect box, float confidence, NSString *text) {
  return @{
    @"text" : text ?: @"",
    @"confidence" : @(confidence),
    @"x" : @(box.origin.x),
    @"y" : @(box.origin.y),
    @"width" : @(box.size.width),
    @"height" : @(box.size.height),
  };
}

int main(int argc, const char *argv[]) {
  @autoreleasepool {
    if (argc < 2) {
      Fail(@"apple_vision_boxes needs at least one image path");
    }
    NSMutableArray *images = [NSMutableArray array];
    for (int index = 1; index < argc; index++) {
      NSString *path = [NSString stringWithUTF8String:argv[index]];
      NSURL *url = [NSURL fileURLWithPath:path];
      VNRecognizeTextRequest *text = [[VNRecognizeTextRequest alloc] init];
      // Accurate, because the fast path crashes inside Vision on some
      // observations, and because a plate half-read is a plate not blurred.
      text.recognitionLevel = VNRequestTextRecognitionLevelAccurate;
      text.recognitionLanguages = @[ @"en-US" ];
      text.usesLanguageCorrection = NO;
      VNDetectFaceRectanglesRequest *faces = [[VNDetectFaceRectanglesRequest alloc] init];

      VNImageRequestHandler *handler = [[VNImageRequestHandler alloc] initWithURL:url options:@{}];
      NSError *error = nil;
      BOOL performed = [handler performRequests:@[ text, faces ] error:&error];
      if (!performed) {
        Fail([NSString stringWithFormat:@"Vision request failed at index %d: %@", index - 1,
                                        error.localizedDescription]);
      }

      NSMutableArray *textBoxes = [NSMutableArray array];
      for (VNRecognizedTextObservation *observation in text.results) {
        NSArray<VNRecognizedText *> *candidates = [observation topCandidates:1];
        NSString *said = candidates.count > 0 ? candidates.firstObject.string : @"";
        [textBoxes addObject:BoxOf(observation.boundingBox, observation.confidence, said)];
      }
      NSMutableArray *faceBoxes = [NSMutableArray array];
      for (VNFaceObservation *observation in faces.results) {
        [faceBoxes addObject:BoxOf(observation.boundingBox, observation.confidence, nil)];
      }
      [images addObject:@{
        @"index" : @(index - 1),
        @"text" : textBoxes,
        @"faces" : faceBoxes,
      }];
    }
    NSError *writeError = nil;
    NSData *json = [NSJSONSerialization dataWithJSONObject:images options:0 error:&writeError];
    if (json == nil) {
      Fail(@"Vision boxes could not be written as JSON");
    }
    fwrite(json.bytes, 1, json.length, stdout);
  }
  return 0;
}
