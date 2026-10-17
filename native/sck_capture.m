#import <AppKit/AppKit.h>
#import <CoreGraphics/CoreGraphics.h>
#import <ScreenCaptureKit/ScreenCaptureKit.h>
#import <CoreMedia/CoreMedia.h>
#import <CoreVideo/CoreVideo.h>
#import <string.h>
#import <pthread.h>

static void wait_sem(dispatch_semaphore_t sem, double seconds) {
  CFAbsoluteTime deadline = CFAbsoluteTimeGetCurrent() + seconds;
  while (CFAbsoluteTimeGetCurrent() < deadline) {
    if (dispatch_semaphore_wait(sem, DISPATCH_TIME_NOW) == 0) {
      return;
    }
    if (pthread_main_np()) {
      [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode
                               beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.02]];
    } else if (dispatch_semaphore_wait(sem, dispatch_time(DISPATCH_TIME_NOW, 20 * NSEC_PER_MSEC)) == 0) {
      return;
    }
  }
}

typedef void (*SCKFrameCallback)(const uint8_t *bgra, int width, int height, int stride, void *ctx);

static id gGrabber = nil;

@interface AmpilightGrabber : NSObject <SCStreamOutput, SCStreamDelegate>
@property(nonatomic, assign) SCKFrameCallback callback;
@property(nonatomic, assign) void *ctx;
@property(nonatomic, strong) SCStream *stream;
@end

@implementation AmpilightGrabber

- (void)stream:(SCStream *)stream
    didOutputSampleBuffer:(CMSampleBufferRef)sampleBuffer
                   ofType:(SCStreamOutputType)type {
  if (type != SCStreamOutputTypeScreen || self.callback == NULL) {
    return;
  }
  CVImageBufferRef image = CMSampleBufferGetImageBuffer(sampleBuffer);
  if (image == NULL) {
    return;
  }
  CVPixelBufferLockBaseAddress(image, kCVPixelBufferLock_ReadOnly);
  const uint8_t *base = CVPixelBufferGetBaseAddress(image);
  int width = (int)CVPixelBufferGetWidth(image);
  int height = (int)CVPixelBufferGetHeight(image);
  int stride = (int)CVPixelBufferGetBytesPerRow(image);
  if (base != NULL && width > 0 && height > 0 && stride >= width * 4) {
    self.callback(base, width, height, stride, self.ctx);
  }
  CVPixelBufferUnlockBaseAddress(image, kCVPixelBufferLock_ReadOnly);
}

@end

static void copy_error(NSError *error, char *errbuf, int errlen) {
  if (errbuf == NULL || errlen <= 0) {
    return;
  }
  NSString *text = error.localizedDescription ?: @"неизвестная ошибка захвата";
  strncpy(errbuf, text.UTF8String, (size_t)errlen - 1);
  errbuf[errlen - 1] = 0;
}

int sck_start(uint32_t displayID, int maxEdge, int fps, SCKFrameCallback callback, void *ctx,
              char *errbuf, int errlen) {
  if (errbuf && errlen > 0) {
    errbuf[0] = 0;
  }
  __block int result = 4;
  dispatch_semaphore_t sem = dispatch_semaphore_create(0);
  if (pthread_main_np()) {
    [NSApplication sharedApplication];
  }

  [SCShareableContent getShareableContentWithCompletionHandler:^(SCShareableContent *content,
                                                                  NSError *error) {
    if (error != nil || content == nil || content.displays.count == 0) {
      copy_error(error, errbuf, errlen);
      result = 1;
      dispatch_semaphore_signal(sem);
      return;
    }

    SCDisplay *display = content.displays.firstObject;
    if (displayID != 0) {
      for (SCDisplay *candidate in content.displays) {
        if (candidate.displayID == displayID) {
          display = candidate;
          break;
        }
      }
    }

    NSInteger width = display.width;
    NSInteger height = display.height;
    NSInteger limit = maxEdge > 0 ? maxEdge : 1600;
    if (width > limit || height > limit) {
      double scale = (double)limit / (double)MAX(width, height);
      width = MAX(2, (NSInteger)(width * scale));
      height = MAX(2, (NSInteger)(height * scale));
    }
    width &= ~1;
    height &= ~1;

    SCContentFilter *filter = [[SCContentFilter alloc] initWithDisplay:display excludingWindows:@[]];
    SCStreamConfiguration *config = [SCStreamConfiguration new];
    config.width = width;
    config.height = height;
    // 0 — частота самого экрана. Иначе 1/fps, не выше.
    config.minimumFrameInterval = fps >= 60 ? kCMTimeZero : CMTimeMake(1, fps > 0 ? fps : 60);
    config.pixelFormat = kCVPixelFormatType_32BGRA;
    config.colorSpaceName = kCGColorSpaceSRGB;
    if (@available(macOS 15.0, *)) {
      config.captureDynamicRange = SCCaptureDynamicRangeSDR;
    }
    config.showsCursor = YES;
    config.queueDepth = 3;

    AmpilightGrabber *grabber = [AmpilightGrabber new];
    grabber.callback = callback;
    grabber.ctx = ctx;
    grabber.stream = [[SCStream alloc] initWithFilter:filter configuration:config delegate:nil];

    dispatch_queue_attr_t attr = dispatch_queue_attr_make_with_qos_class(
        DISPATCH_QUEUE_SERIAL, QOS_CLASS_USER_INTERACTIVE, 0);
    dispatch_queue_t queue = dispatch_queue_create("ampilight.sck", attr);
    NSError *addError = nil;
    BOOL added = [grabber.stream addStreamOutput:grabber
                                            type:SCStreamOutputTypeScreen
                              sampleHandlerQueue:queue
                                           error:&addError];
    if (!added || addError != nil) {
      copy_error(addError, errbuf, errlen);
      result = 2;
      dispatch_semaphore_signal(sem);
      return;
    }

    gGrabber = grabber;
    [grabber.stream startCaptureWithCompletionHandler:^(NSError *startError) {
      if (startError != nil) {
        copy_error(startError, errbuf, errlen);
        gGrabber = nil;
        result = 3;
      } else {
        result = 0;
      }
      dispatch_semaphore_signal(sem);
    }];
  }];

  wait_sem(sem, 45);
  return result;
}

int sck_request_access(void) {
  if (CGPreflightScreenCaptureAccess()) {
    return 1;
  }
  return CGRequestScreenCaptureAccess() ? 2 : 0;
}

int sck_preflight(char *errbuf, int errlen) {
  if (errbuf && errlen > 0) {
    errbuf[0] = 0;
  }
  __block int result = 4;
  dispatch_semaphore_t sem = dispatch_semaphore_create(0);
  if (pthread_main_np()) {
    [NSApplication sharedApplication];
  }
  [SCShareableContent getShareableContentWithCompletionHandler:^(SCShareableContent *content,
                                                                  NSError *error) {
    if (error != nil || content == nil || content.displays.count == 0) {
      copy_error(error, errbuf, errlen);
      result = 1;
    } else {
      result = 0;
    }
    dispatch_semaphore_signal(sem);
  }];
  wait_sem(sem, 60);
  return result;
}

void sck_stop(void) {
  AmpilightGrabber *grabber = gGrabber;
  gGrabber = nil;
  if (grabber == nil) {
    return;
  }
  grabber.callback = NULL;
  dispatch_semaphore_t sem = dispatch_semaphore_create(0);
  [grabber.stream stopCaptureWithCompletionHandler:^(NSError *error) {
    (void)error;
    dispatch_semaphore_signal(sem);
  }];
  wait_sem(sem, 2);
}
