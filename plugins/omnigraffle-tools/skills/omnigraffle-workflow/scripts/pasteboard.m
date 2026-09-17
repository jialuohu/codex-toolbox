#import <Cocoa/Cocoa.h>
#import <ApplicationServices/ApplicationServices.h>
#include <sys/stat.h>
#include <unistd.h>
// Opaque stock-app payloads only. Never deserialize NSKeyedArchiver objects.
static void emit(NSDictionary *d) { NSData *b=[NSJSONSerialization dataWithJSONObject:d options:0 error:nil]; fwrite(b.bytes,1,b.length,stdout); puts(""); }
static int fail(NSString *s) {emit(@{@"status":@"error",@"message":s});return 2;}
static int clipboardChanged(void) {emit(@{@"status":@"restore_skipped",@"reason":@"clipboard_changed"});return 3;}
static BOOL writeNew(NSData *data, NSString *path) {
 return data && [data writeToFile:path options:NSDataWritingWithoutOverwriting error:nil] && chmod(path.fileSystemRepresentation,0600)==0;
}
// Read persisted configuration only. Never change preferences or grant access.
// This rejects known executable hooks, but trusted TeX and runtime remain required.
static NSDictionary *compositionProfile(void) {
 CFStringRef domain=CFSTR("fr.chachatelier.pierre.LaTeXiT");
 NSArray *configs=CFBridgingRelease(CFPreferencesCopyAppValue(CFSTR("CompositionConfigurations"),domain));
 NSNumber *index=CFBridgingRelease(CFPreferencesCopyAppValue(CFSTR("CompositionConfigurationDocumentIndexKey"),domain));
 // LaTeXiT 2.16.6 registers index zero as its default (PreferencesController.m).
 if(!index)index=@0;
 if(![configs isKindOfClass:NSArray.class]||!configs.count||configs.count>64||![index isKindOfClass:NSNumber.class]||index.integerValue<0||index.unsignedIntegerValue>=configs.count)
  return @{@"status":@"unavailable"};
 NSDictionary *profile=configs[index.unsignedIntegerValue];
 if(![profile isKindOfClass:NSDictionary.class]||![profile[@"compositionMode"] isKindOfClass:NSNumber.class]||[profile[@"compositionMode"] intValue]!=0)return @{@"status":@"unsafe"};
 NSDictionary *scripts=profile[@"additionalProcessingScripts"], *arguments=profile[@"programArguments"];
 if(![scripts isKindOfClass:NSDictionary.class]||![arguments isKindOfClass:NSDictionary.class])return @{@"status":@"unavailable"};
 for(id key in scripts){NSDictionary *script=scripts[key];if(![script isKindOfClass:NSDictionary.class]||![script[@"enabled"] isKindOfClass:NSNumber.class]||[script[@"enabled"] boolValue])return @{@"status":@"unsafe"};}
 for(id key in arguments){NSArray *args=arguments[key];if(![args isKindOfClass:NSArray.class])return @{@"status":@"unsafe"};for(id arg in args)if(![arg isKindOfClass:NSString.class]||![arg isEqual:@"-no-shell-escape"])return @{@"status":@"unsafe"};}
 for(NSString *key in @[@"pdfLatexPath",@"gsPath"]){NSString *path=profile[key];if(![path isKindOfClass:NSString.class]||!path.isAbsolutePath||![NSFileManager.defaultManager isExecutableFileAtPath:path])return @{@"status":@"unavailable"};}
 return @{@"status":@"safe",@"trusted_tex_required":@YES};
}
int main(int argc, const char **argv) { @autoreleasepool { @try {
 if(argc<2)return fail(@"Expected operation");
 NSString *op=@(argv[1]);
 if([op isEqual:@"readiness"]&&argc==2) {
  NSDictionary *session=CFBridgingRelease(CGSessionCopyCurrentDictionary());
  BOOL unlocked=session && [session[(__bridge NSString *)kCGSessionOnConsoleKey] boolValue] && ![session[@"CGSSessionScreenIsLocked"] boolValue] && [session[(__bridge NSString *)kCGSessionUserIDKey] unsignedIntValue]==geteuid();
  NSMutableArray *apps=[NSMutableArray array];
  for(NSRunningApplication *app in NSWorkspace.sharedWorkspace.runningApplications) {
   if([@[@"com.omnigroup.OmniGraffle7",@"fr.chachatelier.pierre.LaTeXiT"] containsObject:app.bundleIdentifier?:@""])
    [apps addObject:@{@"bundle_id":app.bundleIdentifier,@"pid":@(app.processIdentifier),@"path":app.bundleURL.path?:@""}];
  }
  emit(@{@"status":@"ok",@"unlocked":@(unlocked),@"accessibility":@(AXIsProcessTrusted()),@"apps":apps,@"composition_profile":compositionProfile()});return 0;
 }
 if(argc<3)return fail(@"Missing path");
 NSString *path=@(argv[2]); NSPasteboard *pb=NSPasteboard.generalPasteboard;
 NSInteger count=pb.changeCount;
 if([op isEqual:@"snapshot"]&&argc==3) {
  NSMutableArray *saved=[NSMutableArray array];NSUInteger size=0, representations=0, unavailableLegacyAliases=0;
  for(NSPasteboardItem *item in pb.pasteboardItems) {
   if(saved.count>=128)return fail(@"Too many clipboard items");
   NSMutableDictionary *types=[NSMutableDictionary dictionary];
   for(NSString *type in item.types) {
    if(++representations>1024)return fail(@"Too many clipboard representations");
    NSData *d=[item dataForType:type];
    if(!d && [type isEqual:@"com.apple.traditional-mac-plain-text"]) {
     // macOS may advertise the legacy TEXT alias even when its conversion
     // cannot be materialized. Preserve the complete Unicode representation;
     // never replace missing data with empty bytes or omit another format.
     NSData *utf8=[item dataForType:NSPasteboardTypeString];
     if([item.types containsObject:NSPasteboardTypeString] && utf8 && utf8.length<=64*1024*1024 && [[NSString alloc] initWithData:utf8 encoding:NSUTF8StringEncoding]) {unavailableLegacyAliases++;continue;}
    }
    if(!d)return fail(@"Unavailable clipboard representation");
    size+=d.length;if(size>64*1024*1024)return fail(@"Clipboard too large");types[type]=d;
   }
   [saved addObject:types];
  }
  if(pb.changeCount!=count)return fail(@"Clipboard changed during snapshot");
  NSData *data=[NSPropertyListSerialization dataWithPropertyList:saved format:NSPropertyListBinaryFormat_v1_0 options:0 error:nil];
  if(!writeNew(data,path))return fail(@"Snapshot destination exists or write failed");
  emit(@{@"status":@"snapshot_saved",@"change_count":@(count),@"unavailable_legacy_text_aliases":@(unavailableLegacyAliases)});return 0;
 }
 if([op isEqual:@"capture"]&&argc==4) {
  if(count!=[@(argv[3]) integerValue])return fail(@"Clipboard changed before capture");
  NSData *linkData=[pb dataForType:@"LinkBackData"];
  if(!linkData||linkData.length>17*1024*1024)return fail(@"LinkBack record too large or missing");
  NSDictionary *link=[NSPropertyListSerialization propertyListWithData:linkData options:NSPropertyListImmutable format:nil error:nil];
  NSData *pdf=[pb dataForType:NSPasteboardTypePDF];
  if(![link isKindOfClass:NSDictionary.class])return fail(@"Malformed LinkBack envelope");
  if(![link[@"bundleId"] isEqual:@"fr.chachatelier.pierre.LaTeXiT"])return fail(@"Unexpected LinkBack application owner");
  if(![link[@"serverName"] isEqual:@"LaTeXiT"])return fail(@"Unexpected LinkBack server name");
  if(![link[@"appData"] isKindOfClass:NSData.class])return fail(@"Missing opaque LinkBack application data");
  if(pdf.length<5||memcmp(pdf.bytes,"%PDF-",5)){
   fprintf(stderr,"Copied PDF bytes: %lu; PDF type declared: %s\n",(unsigned long)pdf.length,[pb.types containsObject:NSPasteboardTypePDF]?"yes":"no");
   return fail(@"Missing or invalid copied PDF data");
  }
  if(pdf.length>8*1024*1024||[link[@"appData"] length]>16*1024*1024)return fail(@"Equation payload too large");
  if(pb.changeCount!=count)return fail(@"Clipboard changed during capture");
  if(![NSFileManager.defaultManager createDirectoryAtPath:path withIntermediateDirectories:NO attributes:@{NSFilePosixPermissions:@0700} error:nil])return fail(@"Capture destination exists or mkdir failed");
  NSData *raw=[NSPropertyListSerialization dataWithPropertyList:link format:NSPropertyListBinaryFormat_v1_0 options:0 error:nil];
  if(!writeNew(pdf,[path stringByAppendingPathComponent:@"equation.pdf"])||!writeNew(raw,[path stringByAppendingPathComponent:@"linkback.plist"])||!writeNew(link[@"appData"],[path stringByAppendingPathComponent:@"equation.archive"]))return fail(@"Capture write incomplete; reconcile");
  emit(@{@"status":@"captured",@"change_count":@(count),@"server":link[@"serverName"],@"bundle_id":link[@"bundleId"],@"pdf_bytes":@(pdf.length)});return 0;
 }
 if([op isEqual:@"restore"]&&argc==4) {
  if(pb.changeCount!=[@(argv[3]) integerValue])return clipboardChanged();
  NSDictionary *attrs=[NSFileManager.defaultManager attributesOfItemAtPath:path error:nil];
  if(![attrs[NSFileType] isEqual:NSFileTypeRegular]||[attrs[NSFileSize] unsignedLongLongValue]>65*1024*1024||[attrs[NSFileOwnerAccountID] unsignedIntValue]!=geteuid()||[attrs[NSFilePosixPermissions] unsignedIntValue]&0077)return fail(@"Invalid snapshot");
  NSArray *saved=[NSPropertyListSerialization propertyListWithData:[NSData dataWithContentsOfFile:path] options:NSPropertyListImmutable format:nil error:nil];
  if(![saved isKindOfClass:NSArray.class]||saved.count>128)return fail(@"Invalid snapshot data");
  NSMutableArray *items=[NSMutableArray array];NSUInteger size=0,representations=0;
  for(NSDictionary *types in saved){
   if(![types isKindOfClass:NSDictionary.class])return fail(@"Invalid snapshot item");
   NSPasteboardItem *item=[[NSPasteboardItem alloc]init];
   for(NSString *type in types){
    if(++representations>1024||![type isKindOfClass:NSString.class]||![types[type] isKindOfClass:NSData.class])return fail(@"Invalid snapshot representation");
    size+=[types[type] length];if(size>64*1024*1024)return fail(@"Snapshot too large");
    if(![item setData:types[type] forType:type])return fail(@"Representation restore failed");
   }
   [items addObject:item];
  }
  if(pb.changeCount!=count)return clipboardChanged();
  [pb clearContents];BOOL ok=items.count?[pb writeObjects:items]:YES;
  emit(@{@"status":ok?@"restored":@"restore_failed",@"change_count":@(pb.changeCount)});return ok?0:2;
 }
 return fail(@"Unknown operation");
 }@catch(NSException *e){return fail(@"Native helper exception");} } }
