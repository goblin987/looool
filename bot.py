from telegram.ext import Application, CommandHandler, CallbackQueryHandler

# Import configurations and utilities
from config_and_utils import (
    TELEGRAM_TOKEN,
    ADMIN_TELEGRAM_ID_STR,
    ADMIN_IDS, # This is a list, will be populated
    logger,
    load_translations
)

# Import DB operations
from db_operations import init_db

# Import handlers and conversation objects
from handlers import (
    start_command_handler,
    admin_command_entry,
    lang_conv,
    order_conv,
    admin_add_prod_conv,
    admin_manage_prod_conv,
    admin_clear_orders_conv,
    my_orders_direct_cb,
    admin_view_orders_direct_cb,
    admin_shop_list_direct_cb
)


def main() -> None:
    # --- Initial Setup ---
    if not TELEGRAM_TOKEN:
        logger.critical("TELEGRAM_TOKEN missing!")
        return
    if not ADMIN_TELEGRAM_ID_STR:
        logger.critical("ADMIN_TELEGRAM_ID missing!")
        return

    try:
        # Populate ADMIN_IDS (which is defined in config_and_utils)
        # ADMIN_IDS from config_and_utils is a global list, so we modify it directly.
        # Clear it first in case this main() is somehow called multiple times (unlikely for typical bot script)
        ADMIN_IDS.clear()
        parsed_ids = [int(aid.strip()) for aid in ADMIN_TELEGRAM_ID_STR.split(',') if aid.strip()]
        ADMIN_IDS.extend(parsed_ids)
        if not ADMIN_IDS:
            logger.warning("ADMIN_TELEGRAM_ID is set but parsed to an empty list. No admins configured.")
    except ValueError:
        logger.critical("Admin IDs invalid! Must be comma-separated numbers.")
        return

    load_translations()
    if not ("en" in globals().get("translations", {}) and "lt" in globals().get("translations", {})): # Check if translations actually loaded
         # The check is now inside config_and_utils.load_translations
         # Re-check here or trust the log from there.
         # For safety, can add:
         from config_and_utils import translations as loaded_translations # get the potentially updated global
         if not loaded_translations.get("en") or not loaded_translations.get("lt"):
            logger.critical("Core translations missing after load attempt in main! Bot cannot function correctly.")
            return


    init_db() # Initialize database

    # --- Application Setup ---
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # --- Add Handlers ---
    application.add_handler(CommandHandler("start", start_command_handler))
    application.add_handler(CommandHandler("admin", admin_command_entry))

    application.add_handler(lang_conv)
    application.add_handler(order_conv)
    application.add_handler(admin_add_prod_conv)
    application.add_handler(admin_manage_prod_conv)
    application.add_handler(admin_clear_orders_conv)

    # Direct callback handlers
    application.add_handler(CallbackQueryHandler(my_orders_direct_cb, pattern="^my_orders_direct_cb$"))
    application.add_handler(CallbackQueryHandler(admin_view_orders_direct_cb, pattern="^admin_view_orders_direct_cb$"))
    application.add_handler(CallbackQueryHandler(admin_shop_list_direct_cb, pattern="^admin_shop_list_direct_cb$"))

    logger.info("Bot starting with modularized structure...")
    application.run_polling()

if __name__ == "__main__":
    main()