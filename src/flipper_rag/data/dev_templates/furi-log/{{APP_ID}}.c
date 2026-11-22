#include <furi.h>

int32_t {{ENTRY}}(void* context) {
    UNUSED(context);
    FuriString* message = furi_string_alloc_set_str("{{APP_NAME}}");
    FURI_LOG_I("DevTutorial", "%s", furi_string_get_cstr(message));
    furi_string_free(message);
    return 0;
}
