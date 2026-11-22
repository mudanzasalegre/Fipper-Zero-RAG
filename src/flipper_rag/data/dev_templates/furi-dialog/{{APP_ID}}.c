#include <furi.h>
#include <dialogs/dialogs.h>

int32_t {{ENTRY}}(void* context) {
    UNUSED(context);
    DialogsApp* dialogs = furi_record_open(RECORD_DIALOGS);
    DialogMessage* message = dialog_message_alloc();
    dialog_message_set_header(message, "{{APP_NAME}}", 64, 12, AlignCenter, AlignTop);
    dialog_message_set_text(message, "Hello from Furi!", 64, 32, AlignCenter, AlignCenter);
    dialog_message_show(dialogs, message);
    dialog_message_free(message);
    furi_record_close(RECORD_DIALOGS);
    return 0;
}
