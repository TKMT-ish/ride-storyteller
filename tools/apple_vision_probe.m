#import <Foundation/Foundation.h>
#import <Vision/Vision.h>
#include <string.h>

static void Fail(NSString *message) {
    NSData *data = [[message stringByAppendingString:@"\n"] dataUsingEncoding:NSUTF8StringEncoding];
    [[NSFileHandle fileHandleWithStandardError] writeData:data];
    exit(1);
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        BOOL includeDistances = YES;
        NSInteger imageStart = 1;
        if (argc >= 2 && strcmp(argv[1], "--no-distances") == 0) {
            includeDistances = NO;
            imageStart = 2;
        }
        if (argc <= imageStart) {
            Fail(@"usage: apple-vision-probe <image> [<image> ...]");
        }
        if (@available(macOS 15.0, *)) {
            NSMutableArray<NSDictionary *> *items = [NSMutableArray array];
            NSMutableArray<VNFeaturePrintObservation *> *features = [NSMutableArray array];

            for (NSInteger index = imageStart; index < argc; index++) {
                NSString *path = [NSString stringWithUTF8String:argv[index]];
                NSURL *url = [NSURL fileURLWithPath:path];
                VNCalculateImageAestheticsScoresRequest *aesthetics =
                    [[VNCalculateImageAestheticsScoresRequest alloc] init];
                VNClassifyImageRequest *classification = [[VNClassifyImageRequest alloc] init];
                classification.revision = VNClassifyImageRequestRevision2;
                VNGenerateImageFeaturePrintRequest *feature = nil;
                if (includeDistances) {
                    feature = [[VNGenerateImageFeaturePrintRequest alloc] init];
                    feature.revision = VNGenerateImageFeaturePrintRequestRevision2;
                }
                VNImageRequestHandler *handler =
                    [[VNImageRequestHandler alloc] initWithURL:url options:@{}];
                NSMutableArray<VNRequest *> *requests =
                    [NSMutableArray arrayWithObjects:aesthetics, classification, nil];
                if (feature != nil) {
                    [requests addObject:feature];
                }
                NSError *requestError = nil;
                BOOL performed = [handler performRequests:requests
                                                     error:&requestError];
                if (!performed) {
                    Fail([NSString stringWithFormat:@"Vision request failed at index %ld: %@",
                                                    (long)(index - imageStart),
                                                    requestError.localizedDescription]);
                }

                VNImageAestheticsScoresObservation *aestheticsResult =
                    aesthetics.results.firstObject;
                VNFeaturePrintObservation *featureResult = feature.results.firstObject;
                if (aestheticsResult == nil || (includeDistances && featureResult == nil)) {
                    Fail([NSString stringWithFormat:@"Vision returned incomplete results at index %ld",
                                                    (long)(index - imageStart)]);
                }

                NSMutableArray<NSDictionary *> *labels = [NSMutableArray array];
                for (VNClassificationObservation *result in classification.results) {
                    if (result.confidence < 0.02 || labels.count >= 12) {
                        continue;
                    }
                    [labels addObject:@{
                        @"identifier": result.identifier,
                        @"confidence": @(result.confidence),
                    }];
                }
                [items addObject:@{
                    @"index": @(index - imageStart),
                    @"aestheticScore": @(aestheticsResult.overallScore),
                    @"isUtility": @(aestheticsResult.isUtility),
                    @"classifications": labels,
                }];
                if (includeDistances) {
                    [features addObject:featureResult];
                }
            }

            NSMutableArray<NSDictionary *> *distances = [NSMutableArray array];
            if (includeDistances) {
                for (NSInteger first = 0; first < features.count; first++) {
                    for (NSInteger second = first + 1; second < features.count; second++) {
                        float distance = 0.0f;
                        NSError *distanceError = nil;
                        BOOL compared = [features[first] computeDistance:&distance
                                               toFeaturePrintObservation:features[second]
                                                                   error:&distanceError];
                        if (!compared) {
                            Fail([NSString stringWithFormat:@"Vision feature comparison failed: %@",
                                                            distanceError.localizedDescription]);
                        }
                        [distances addObject:@{
                            @"firstIndex": @(first),
                            @"secondIndex": @(second),
                            @"distance": @(distance),
                        }];
                    }
                }
            }

            NSDictionary *payload = @{
                @"schemaVersion": @"ride-apple-vision-v1",
                @"items": items,
                @"distances": distances,
            };
            NSError *encodingError = nil;
            NSData *json = [NSJSONSerialization dataWithJSONObject:payload
                                                           options:NSJSONWritingSortedKeys
                                                             error:&encodingError];
            if (json == nil) {
                Fail([NSString stringWithFormat:@"JSON encoding failed: %@",
                                                encodingError.localizedDescription]);
            }
            [[NSFileHandle fileHandleWithStandardOutput] writeData:json];
            [[NSFileHandle fileHandleWithStandardOutput]
                writeData:[@"\n" dataUsingEncoding:NSUTF8StringEncoding]];
            return 0;
        }
        Fail(@"apple-vision-probe requires macOS 15 or later");
    }
}
