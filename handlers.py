# handlers.py

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, Message
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
)

# Import utilities and configs
from config_and_utils import logger, _, ADMIN_IDS, get_user_language

# Import DB operations
import db_operations

# --- Conversation States ---
(SELECT_LANGUAGE_STATE,
 ORDER_FLOW_BROWSING_PRODUCTS, ORDER_FLOW_SELECTING_QUANTITY, ORDER_FLOW_VIEWING_CART,
 ADMIN_MAIN_PANEL_STATE,
 ADMIN_ADD_PROD_NAME, ADMIN_ADD_PROD_PRICE,
 ADMIN_MANAGE_PROD_LIST, ADMIN_MANAGE_PROD_OPTIONS, ADMIN_MANAGE_PROD_EDIT_PRICE, ADMIN_MANAGE_PROD_DELETE_CONFIRM,
 ADMIN_CLEAR_ORDERS_CONFIRM
) = range(12)


# --- Helper: Display Main Menu ---
async def display_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, edit_message: bool = False):
    user = update.effective_user
    if not user: logger.error("display_main_menu called without effective_user"); return
    user_id = user.id
    # Ensure language is set in context for _ to work correctly if it's the first interaction
    if 'language_code' not in context.user_data:
        context.user_data['language_code'] = await get_user_language(context, user_id)


    kb = [
        [InlineKeyboardButton(await _(context,"browse_products_button",user_id=user_id),callback_data="order_flow_browse_entry")],
        [InlineKeyboardButton(await _(context,"view_cart_button",user_id=user_id),callback_data="order_flow_view_cart_direct_entry")], # This will lead to manage_cart
        [InlineKeyboardButton(await _(context,"my_orders_button",user_id=user_id),callback_data="my_orders_direct_cb")],
        [InlineKeyboardButton(await _(context,"set_language_button",user_id=user_id),callback_data="select_language_entry")]
    ]
    welcome = await _(context,"welcome_message",user_id=user_id,user_mention=user.mention_html())
    target_message_obj = update.callback_query.message if edit_message and update.callback_query else update.message

    try:
        if edit_message and target_message_obj:
            await target_message_obj.edit_text(welcome,reply_markup=InlineKeyboardMarkup(kb),parse_mode='HTML')
        elif update.message:
            await update.message.reply_html(welcome,reply_markup=InlineKeyboardMarkup(kb))
        elif user_id :
            await context.bot.send_message(chat_id=user_id,text=welcome,reply_markup=InlineKeyboardMarkup(kb),parse_mode='HTML')
    except Exception as e:
        logger.warning(f"Display main menu error (edit={edit_message}, target_message_obj exists: {bool(target_message_obj)}): {e}")
        if user_id and not (edit_message and target_message_obj) and not update.message :
            try:
                await context.bot.send_message(chat_id=user_id,text=welcome,reply_markup=InlineKeyboardMarkup(kb),parse_mode='HTML')
            except Exception as send_e:
                logger.error(f"Fallback display_main_menu send error: {send_e}")

# --- Start Command & General Back to Main Menu ---
async def start_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user: logger.error("start_command: effective_user is None"); return

    await db_operations.ensure_user_exists(user.id, user.first_name or "", user.username or "", context)
    context.user_data['language_code'] = await get_user_language(context, user.id)


    lang_code = context.user_data.get('language_code')
    cart_data = context.user_data.get('cart')
    # Preserve last_product_list_message_id if user /starts mid-flow, but usually it should be cleared
    # For a clean /start, it's better to clear it.
    keys_to_clear = [k for k in context.user_data if k not in ['language_code', 'cart'] and not k.startswith('_')]
    for key_to_clear in keys_to_clear:
        context.user_data.pop(key_to_clear, None)
    context.user_data.pop('last_product_list_message_id', None) # Explicitly clear this on /start

    if lang_code: context.user_data['language_code'] = lang_code
    if cart_data is not None: context.user_data['cart'] = cart_data


    await display_main_menu(update, context, edit_message=False)

async def back_to_main_menu_cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query: await update.callback_query.answer()

    lang_code = context.user_data.get('language_code')
    cart_data = context.user_data.get('cart')
    keys_to_clear = [k for k in context.user_data if k not in ['language_code', 'cart'] and not k.startswith('_')]
    for key_to_clear in keys_to_clear:
        context.user_data.pop(key_to_clear, None)
    context.user_data.pop('last_product_list_message_id', None)

    if lang_code: context.user_data['language_code'] = lang_code
    elif update.effective_user:
         context.user_data['language_code'] = await get_user_language(context, update.effective_user.id)

    if cart_data is not None: context.user_data['cart'] = cart_data


    await display_main_menu(update,context,edit_message=bool(update.callback_query))
    return ConversationHandler.END

# --- Language Selection Flow ---
async def select_language_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q=update.callback_query;await q.answer();uid=q.from_user.id;logger.info(f"User {uid} entering language selection.")
    kb=[[InlineKeyboardButton("English 🇬🇧",callback_data="lang_select_en")],[InlineKeyboardButton("Lietuvių 🇱🇹",callback_data="lang_select_lt")],[InlineKeyboardButton(await _(context,"back_button",user_id=uid,default="⬅️ Back"),callback_data="main_menu_direct_cb_ender")]]
    # When selecting language, we might be editing the main product list message.
    # It's safer to store its ID before editing for language, then restore if needed, or just send new main menu.
    # For now, display_main_menu after language selection will handle it.
    await q.edit_message_text(await _(context,"choose_language",user_id=uid),reply_markup=InlineKeyboardMarkup(kb));return SELECT_LANGUAGE_STATE

async def language_selected_state(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q=update.callback_query;await q.answer();code=q.data.split('_')[-1];uid=q.from_user.id
    context.user_data['language_code']=code
    await db_operations.set_user_language_db(uid,code)
    name="English" if code=="en" else "Lietuvių"
    # The message "Language set to..." should ideally be shown, then main menu.
    # For simplicity, directly display main menu. The previous edit will be overwritten.
    # await q.edit_message_text(await _(context,"language_set_to",user_id=uid,language_name=name))
    # context.user_data.pop('last_product_list_message_id', None) # Clean this if navigating away
    # await display_main_menu(update,context,edit_message=True); # Edit the "choose language" message
    
    # Let's show the confirmation then the main menu
    await q.edit_message_text(await _(context,"language_set_to",user_id=uid,language_name=name))
    # Then, send the main menu as a new message to avoid issues with the previous message being the product list
    context.user_data.pop('last_product_list_message_id', None)
    temp_update_for_main_menu = Update(update.update_id, message=q.message) # Use original message for context
    if not hasattr(temp_update_for_main_menu, 'effective_user') or not temp_update_for_main_menu.effective_user:
         temp_update_for_main_menu.effective_user = q.from_user
    await display_main_menu(temp_update_for_main_menu, context, edit_message=False) # Send new

    return ConversationHandler.END

# --- USER ORDER FLOW (COMBINED CART & PRODUCTS) ---

async def display_cart_and_products(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, edit_message_id: int = None) -> int:
    cart = context.user_data.get('cart', [])
    query = update.callback_query

    cart_text_parts = []
    if not cart:
        cart_text_parts.append(await _(context, "cart_empty", user_id=user_id))
    else:
        cart_text_parts.append(f"🛒 {await _(context, 'your_cart_title', user_id=user_id)}")
        cart_text_parts.append("------------------------------------")
        total_price = 0.0 # Initialize as float
        for i, item in enumerate(cart):
            item_total = item['price'] * item['quantity']
            total_price += item_total
            cart_text_parts.append(f"| {i+1}. {item['name']} ({item['quantity']:.2f} kg) - {item_total:.2f} EUR")
        cart_text_parts.append("------------------------------------")
        cart_text_parts.append(f"| {await _(context, 'cart_total', user_id=user_id, total_price=total_price)}") # Pass float
        cart_text_parts.append("------------------------------------")
    cart_display_text = "\n".join(cart_text_parts)

    products = db_operations.get_products_from_db(available_only=True)
    product_keyboard_buttons = []
    product_list_text_parts = ["\n" + await _(context, "products_title", user_id=user_id)]

    if not products:
        product_list_text_parts.append(await _(context, "no_products_available", user_id=user_id))
    else:
        for pid, name, price, _avail in products:
            product_keyboard_buttons.append([InlineKeyboardButton(f"{name} - {price:.2f} EUR/kg", callback_data=f"order_flow_select_prod_{pid}")])

    full_text_to_send = cart_display_text + "\n" + "\n".join(product_list_text_parts)

    if cart:
        product_keyboard_buttons.append([InlineKeyboardButton(await _(context, "checkout_button", user_id=user_id), callback_data="order_flow_checkout_cb")])
    product_keyboard_buttons.append([InlineKeyboardButton(await _(context, "view_cart_button", user_id=user_id) + " (Manage)", callback_data="order_flow_manage_cart_cb")])
    product_keyboard_buttons.append([InlineKeyboardButton(await _(context, "back_to_main_menu_button", user_id=user_id), callback_data="main_menu_direct_cb_ender")])

    reply_markup = InlineKeyboardMarkup(product_keyboard_buttons)

    chat_id_to_use = user_id # Default
    if query and query.message: chat_id_to_use = query.message.chat_id
    elif update.message: chat_id_to_use = update.message.chat_id
    
    current_message_id_to_edit = edit_message_id
    # If not specifically passed, try to get from context or current query
    if not current_message_id_to_edit:
        if query and query.message:
            current_message_id_to_edit = query.message.message_id
        elif 'last_product_list_message_id' in context.user_data: # Try to reuse last known good message
            current_message_id_to_edit = context.user_data['last_product_list_message_id']


    sent_message_object = None
    try:
        if current_message_id_to_edit:
             await context.bot.edit_message_text(
                chat_id=chat_id_to_use, # Ensure chat_id is correct
                message_id=current_message_id_to_edit,
                text=full_text_to_send,
                reply_markup=reply_markup
            )
             context.user_data['last_product_list_message_id'] = current_message_id_to_edit
        elif update.message: # Called after a text input, like quantity_typed
            sent_message_object = await update.message.reply_text(text=full_text_to_send, reply_markup=reply_markup)
            context.user_data['last_product_list_message_id'] = sent_message_object.message_id
        else: # Fallback, e.g. initial browse_entry if query.message was None
            sent_message_object = await context.bot.send_message(chat_id=user_id, text=full_text_to_send, reply_markup=reply_markup)
            context.user_data['last_product_list_message_id'] = sent_message_object.message_id
    except Exception as e:
        logger.error(f"Error in display_cart_and_products (edit_id={current_message_id_to_edit}, chat_id={chat_id_to_use}): {e}")
        # Fallback: send a new message
        try:
            sent_message_object = await context.bot.send_message(chat_id=user_id, text=full_text_to_send, reply_markup=reply_markup)
            context.user_data['last_product_list_message_id'] = sent_message_object.message_id
            logger.info(f"Sent new message as fallback in display_cart_and_products. New msg_id: {sent_message_object.message_id}")
        except Exception as send_e:
            logger.error(f"Fallback send_message in display_cart_and_products also failed: {send_e}")

    return ORDER_FLOW_BROWSING_PRODUCTS

async def order_flow_browse_entry(update:Update,context:ContextTypes.DEFAULT_TYPE)->int:
    logger.info(f"User {update.effective_user.id} entered order_flow_browse_entry")
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    # When entering, use the current message (from the button press) to edit.
    return await display_cart_and_products(update, context, user_id, edit_message_id=query.message.message_id)

async def order_flow_product_selected(update:Update,context:ContextTypes.DEFAULT_TYPE)->int:
    q=update.callback_query;await q.answer();uid=q.from_user.id
    try:pid=int(q.data.split('_')[-1])
    except (IndexError, ValueError):
        logger.warning(f"Failed to parse product ID: {q.data}")
        return await display_cart_and_products(update, context, uid, edit_message_id=q.message.message_id)
    prod=db_operations.get_product_by_id(pid)
    if not prod:
        # Edit current message to "Product not found", then call display_cart_and_products to refresh
        await q.edit_message_text(await _(context,"product_not_found",user_id=uid,default="Product not found."))
        # A small delay might be needed if Telegram API is too fast, or this edit might be overwritten.
        # For now, let display_cart_and_products handle the refresh.
        return await display_cart_and_products(update, context, uid, edit_message_id=q.message.message_id)

    context.user_data.update({'current_product_id':pid,'current_product_name':prod[1],'current_product_price':prod[2]})
    if q.message:
        context.user_data['last_product_list_message_id'] = q.message.message_id # Store ID of the list we're editing
    await q.edit_message_text(await _(context,"product_selected_prompt",user_id=uid,product_name=prod[1]))
    return ORDER_FLOW_SELECTING_QUANTITY

async def order_flow_quantity_typed(update:Update,context:ContextTypes.DEFAULT_TYPE)->int:
    uid=update.effective_user.id
    q_str=update.message.text
    # This is the ID of the message that prompted for quantity (originally the product list)
    message_to_edit_id = context.user_data.get('last_product_list_message_id')

    try:qnt=float(q_str);assert qnt>0
    except (ValueError, AssertionError):
        await update.message.reply_text(await _(context,"invalid_quantity_prompt",user_id=uid))
        # Re-show the prompt on the original message if we have its ID
        if message_to_edit_id:
            prod_name = context.user_data.get('current_product_name', 'the selected product')
            try:
                await context.bot.edit_message_text(
                    chat_id=update.message.chat_id, # Use current message's chat_id for safety
                    message_id=message_to_edit_id,
                    text=await _(context,"product_selected_prompt",user_id=uid,product_name=prod_name)
                )
            except Exception as e:
                logger.error(f"Error re-editing quantity prompt message {message_to_edit_id}: {e}")
                # If edit fails, send a new prompt
                await context.bot.send_message(chat_id=uid, text=await _(context,"product_selected_prompt",user_id=uid,product_name=prod_name))
        else: # No message_to_edit_id, just send a new prompt
            prod_name = context.user_data.get('current_product_name', 'the selected product')
            await context.bot.send_message(chat_id=uid, text=await _(context,"product_selected_prompt",user_id=uid,product_name=prod_name))
        return ORDER_FLOW_SELECTING_QUANTITY

    pid=context.user_data.get('current_product_id')
    pname=context.user_data.get('current_product_name')
    pprice=context.user_data.get('current_product_price')

    if not all([pid is not None,pname is not None,pprice is not None]):
        await update.message.reply_text(await _(context,"generic_error_message",user_id=uid,default="Error: Product details missing. Please select a product again."))
        # Try to go back to browsing by editing the stored message ID
        return await display_cart_and_products(update, context, uid, edit_message_id=message_to_edit_id)

    cart=context.user_data.setdefault('cart',[])
    found_item = next((item for item in cart if item['id'] == pid), None)
    if found_item:
        found_item['quantity'] += qnt
    else:
        cart.append({'id':pid,'name':pname,'price':pprice,'quantity':qnt})

    try: # Delete the user's message where they typed the quantity
        await context.bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
    except Exception as e:
        logger.warning(f"Could not delete user's quantity message: {e}")

    # After adding to cart, update the main message (which was prompting for quantity)
    # to show the cart and product list again.
    return await display_cart_and_products(update, context, uid, edit_message_id=message_to_edit_id)


# --- DETAILED CART MANAGEMENT FLOW ---
async def order_flow_manage_cart_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    context.user_data.setdefault('cart', [])
    # When managing cart, edit the message that was showing the combined list.
    return await order_flow_display_cart_detailed(update, context, user_id, edit_message_id=query.message.message_id)

async def order_flow_display_cart_detailed(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, edit_message_id: int = None) -> int:
    cart = context.user_data.get('cart', [])
    query = update.callback_query # This function is typically called from a query

    text_to_send_parts = []
    keyboard_buttons = []

    if not cart:
        text_to_send_parts.append(await _(context, "cart_empty", user_id=user_id))
        # Button to go back to the combined cart & product view
        keyboard_buttons.append([InlineKeyboardButton(await _(context, "browse_products_button", user_id=user_id), callback_data="order_flow_browse_return_cb_detailed")])
    else:
        text_to_send_parts.append(await _(context, "your_cart_title", user_id=user_id) + " (Manage Items)")
        text_to_send_parts.append("====================================")
        total_price = 0.0 # Initialize as float
        for i, item in enumerate(cart):
            item_total = item['price'] * item['quantity']
            total_price += item_total
            text_to_send_parts.append(f"{i+1}. {item['name']} - {item['quantity']:.2f} kg x {item['price']:.2f} EUR = {item_total:.2f} EUR")
            keyboard_buttons.append([InlineKeyboardButton(await _(context, "remove_item_button", user_id=user_id, item_index=i+1), callback_data=f"order_flow_remove_item_{i}")])
        text_to_send_parts.append("====================================")
        text_to_send_parts.append(await _(context, "cart_total", user_id=user_id, total_price=total_price)) # Pass float
        text_to_send_parts.append("====================================")
        keyboard_buttons.append([InlineKeyboardButton(await _(context, "checkout_button", user_id=user_id), callback_data="order_flow_checkout_cb")])
        # Button to go back to the combined cart & product view
        keyboard_buttons.append([InlineKeyboardButton(await _(context, "back_to_main_list_button", default="⬅️ Back to Products & Cart View"), callback_data="order_flow_browse_return_cb_detailed")])

    keyboard_buttons.append([InlineKeyboardButton(await _(context, "back_to_main_menu_button", user_id=user_id), callback_data="main_menu_direct_cb_ender")])
    reply_markup = InlineKeyboardMarkup(keyboard_buttons)
    full_text = "\n".join(text_to_send_parts)

    chat_id_to_use = user_id
    if query and query.message: chat_id_to_use = query.message.chat_id
    elif update.message: chat_id_to_use = update.message.chat_id # Should not happen often for this func

    current_message_id_to_edit = edit_message_id
    if not current_message_id_to_edit and query and query.message:
        current_message_id_to_edit = query.message.message_id
    
    try:
        if current_message_id_to_edit:
            await context.bot.edit_message_text(
                chat_id=chat_id_to_use, message_id=current_message_id_to_edit,
                text=full_text, reply_markup=reply_markup
            )
            # This message is now the "detailed cart view", but its ID might still be stored as 'last_product_list_message_id'.
            # This is fine as returning from here will overwrite it with the combined view.
            context.user_data['last_product_list_message_id'] = current_message_id_to_edit
        else:
            sent_msg = await context.bot.send_message(chat_id=user_id, text=full_text, reply_markup=reply_markup)
            context.user_data['last_product_list_message_id'] = sent_msg.message_id
    except Exception as e:
        logger.error(f"Error in order_flow_display_cart_detailed (edit_id={current_message_id_to_edit}): {e}")
        try:
            sent_msg = await context.bot.send_message(chat_id=user_id, text=full_text, reply_markup=reply_markup)
            context.user_data['last_product_list_message_id'] = sent_msg.message_id
        except Exception as send_e:
            logger.error(f"Fallback send in order_flow_display_cart_detailed also failed: {send_e}")
    return ORDER_FLOW_VIEWING_CART

async def order_flow_remove_item_cb(update:Update,context:ContextTypes.DEFAULT_TYPE)->int:
    q=update.callback_query;await q.answer();uid=q.from_user.id
    try:idx=int(q.data.split('_')[-1])
    except (IndexError, ValueError):
        logger.warning(f"Failed to parse item index for removal: {q.data}")
        # Re-display detailed cart, editing the current message
        return await order_flow_display_cart_detailed(update,context,uid,edit_message_id=q.message.message_id)

    cart=context.user_data.get('cart',[])
    if 0<=idx<len(cart):
        removed=cart.pop(idx)
        await context.bot.answer_callback_query(q.id, text=await _(context,"item_removed_from_cart",user_id=uid,item_name=removed['name']), show_alert=False)
    else:
        await context.bot.answer_callback_query(q.id, text=await _(context,"invalid_item_to_remove",user_id=uid), show_alert=True)
    # Re-display the detailed cart view, editing the same message
    return await order_flow_display_cart_detailed(update,context,uid,edit_message_id=q.message.message_id)

async def order_flow_checkout_cb(update:Update,context:ContextTypes.DEFAULT_TYPE)->int:
    q=update.callback_query;await q.answer();user=q.from_user;uid=user.id;cart=context.user_data.get('cart',[])
    
    message_to_edit_id = None
    if q and q.message:
        message_to_edit_id = q.message.message_id
    elif 'last_product_list_message_id' in context.user_data: # If checkout from combined view after text input
        message_to_edit_id = context.user_data['last_product_list_message_id']

    if not cart:
        empty_cart_text = await _(context,"cart_empty",user_id=uid)
        # Try to edit the existing message if possible
        if message_to_edit_id:
            try:
                await context.bot.edit_message_text(chat_id=uid, message_id=message_to_edit_id, text=empty_cart_text, reply_markup=None)
            except Exception: # If edit fails, send new
                await context.bot.send_message(chat_id=uid, text=empty_cart_text)
        else:
            await context.bot.send_message(chat_id=uid, text=empty_cart_text)
        # After showing cart is empty, go back to the combined products/cart view
        return await display_cart_and_products(update, context, uid, edit_message_id=message_to_edit_id)


    uname=(user.full_name or "N/A")
    total_price_float = sum(i['price']*i['quantity'] for i in cart) # Keep as float
    oid=db_operations.save_order_to_db(uid,uname,cart,total_price_float)
    admin_lang_for_notification = ADMIN_IDS[0] if ADMIN_IDS else None

    if oid:
        success_text = await _(context,"order_placed_success",user_id=uid,order_id=oid,total_price=total_price_float) # Pass float
        # Edit the last message (either detailed cart or combined view) to show success
        if message_to_edit_id:
             try:
                await context.bot.edit_message_text(chat_id=uid, message_id=message_to_edit_id, text=success_text, reply_markup=None)
             except Exception: # If edit fails, send as new message
                await context.bot.send_message(chat_id=uid, text=success_text)
        else: # Should ideally not happen if flow is correct
            await context.bot.send_message(chat_id=uid, text=success_text)

        admin_title=await _(context,"admin_new_order_notification_title",user_id=admin_lang_for_notification,order_id=oid,default=f"🔔 New Order #{oid}")
        admin_msg_body = await _(context,"admin_order_from",user_id=admin_lang_for_notification,name=uname,username=(f"@{user.username}" if user.username else "N/A"),customer_id=uid,default=f"From:{uname}...")+"\n\n"+await _(context,"admin_order_items_header",user_id=admin_lang_for_notification,default="Items:")+"\n------------------------------------\n"
        item_lines=[await _(context,"admin_order_item_line_format",user_id=admin_lang_for_notification,index=i+1,item_name=c['name'],quantity=f"{c['quantity']:.2f}",price_per_kg=f"{c['price']:.2f}",item_subtotal=f"{(c['price']*c['quantity']):.2f}",default=f"{i+1}. {c['name']}: ...")for i,c in enumerate(cart)]
        admin_msg_body+= "\n".join(item_lines)+"\n------------------------------------\n"+await _(context,"admin_order_grand_total",user_id=admin_lang_for_notification,total_price=total_price_float,default=f"Total:{total_price_float:.2f} EUR") # Pass float
        full_admin_msg = f"{admin_title}\n{admin_msg_body}"

        if ADMIN_IDS:
            for admin_id_val in ADMIN_IDS:
                try:
                    if len(full_admin_msg) > 4096:
                        for i_part in range(0, len(full_admin_msg), 4096):
                            await context.bot.send_message(chat_id=admin_id_val, text=full_admin_msg[i_part:i_part+4096])
                    else:
                        await context.bot.send_message(chat_id=admin_id_val,text=full_admin_msg)
                except Exception as e:logger.error(f"Failed to notify admin {admin_id_val} about new order {oid}: {e}")

        lang_code = context.user_data.get('language_code')
        keys_to_pop=['cart','current_product_id','current_product_name','current_product_price', 'last_product_list_message_id']
        for k_pop in keys_to_pop: context.user_data.pop(k_pop,None)
        if lang_code: context.user_data['language_code']=lang_code
        
        # Create a temporary update object for display_main_menu if original update was callback
        temp_update_for_main_menu = update
        if update.callback_query:
            temp_update_for_main_menu = Update(update.update_id, message=update.callback_query.message)
            if not hasattr(temp_update_for_main_menu, 'effective_user') or not temp_update_for_main_menu.effective_user:
                 temp_update_for_main_menu.effective_user = update.callback_query.from_user

        await display_main_menu(temp_update_for_main_menu,context,False) # Send new main menu message
    else: # Order saving failed
        error_text = await _(context,"order_placed_error",user_id=uid)
        if message_to_edit_id:
            try:
                await context.bot.edit_message_text(chat_id=uid, message_id=message_to_edit_id, text=error_text)
            except Exception: # If edit fails, send new
                 await context.bot.send_message(chat_id=uid, text=error_text)
        else:
            await context.bot.send_message(chat_id=uid, text=error_text)
        # Go back to combined cart/products view
        return await display_cart_and_products(update, context, uid, edit_message_id=message_to_edit_id)
    return ConversationHandler.END

async def my_orders_direct_cb(update:Update,context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query;await q.answer();uid=q.from_user.id;orders=db_operations.get_user_orders_from_db(uid)
    txt=await _(context,"my_orders_title",user_id=uid,default="Orders:")+"\n\n" if orders else await _(context,"no_orders_yet",user_id=uid)
    if orders:
        for oid,date_str,total_val_float,status_str,items_str in orders:
            txt+=await _(context,"order_details_format",user_id=uid,order_id=oid,date=date_str,status=status_str.capitalize(),total=total_val_float,items=items_str.replace(chr(10), ", ") if items_str else "N/A",default="Order...") # Pass float
    kb=[[InlineKeyboardButton(await _(context,"back_to_main_menu_button",user_id=uid),callback_data="main_menu_direct_cb_ender")]]
    context.user_data.pop('last_product_list_message_id', None)
    await q.edit_message_text(text=txt,reply_markup=InlineKeyboardMarkup(kb))

# --- ADMIN PANEL AND FLOWS ---
# (These admin handlers should be the same as in your previous full handlers.py)
# For brevity, I'm only including the stubs. Make sure you have the full admin handlers here.
async def display_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE, edit_message: bool = False) -> int:
    user = update.effective_user;
    if not user: logger.error("display_admin_panel: effective_user is None"); return ConversationHandler.END
    user_id = user.id
    if not (ADMIN_IDS and user_id in ADMIN_IDS):
        unauth_text = await _(context,"admin_unauthorized",user_id=user_id)
        target_msg_obj = update.callback_query.message if edit_message and update.callback_query else update.message
        if edit_message and target_msg_obj: await target_msg_obj.edit_text(unauth_text)
        elif update.message: await update.message.reply_text(unauth_text)
        elif user_id : await context.bot.send_message(chat_id=user_id, text=unauth_text)
        return ConversationHandler.END

    context.chat_data['user_id_for_translation'] = user_id
    kb = [
        [InlineKeyboardButton(await _(context,"admin_add_product_button",user_id=user_id),callback_data="admin_add_prod_entry_cb")],
        [InlineKeyboardButton(await _(context,"admin_manage_products_button",user_id=user_id),callback_data="admin_manage_prod_list_entry_cb")],
        [InlineKeyboardButton(await _(context,"admin_view_orders_button",user_id=user_id),callback_data="admin_view_orders_direct_cb")],
        [InlineKeyboardButton(await _(context,"admin_shopping_list_button",user_id=user_id),callback_data="admin_shop_list_direct_cb")],
        [InlineKeyboardButton(await _(context,"admin_clear_orders_button", user_id=user_id, default="🧹 Clear Completed Orders"), callback_data="admin_clear_orders_entry_cb")],
        [InlineKeyboardButton(await _(context,"admin_exit_button",user_id=user_id),callback_data="main_menu_direct_cb_ender")]
    ]
    title = await _(context,"admin_panel_title",user_id=user_id)
    target_msg_obj = update.callback_query.message if edit_message and update.callback_query else update.message
    reply_markup = InlineKeyboardMarkup(kb)

    try:
        if edit_message and target_msg_obj: await target_msg_obj.edit_text(title,reply_markup=reply_markup)
        elif update.message : await update.message.reply_text(title,reply_markup=reply_markup)
        elif user_id: await context.bot.send_message(chat_id=user_id, text=title,reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"Display admin panel error (edit={edit_message}): {e}")
        if user_id and not (edit_message and target_msg_obj) and not update.message :
            try: await context.bot.send_message(chat_id=user_id, text=title,reply_markup=reply_markup)
            except Exception as send_e: logger.error(f"Fallback display_admin_panel send error: {send_e}")
    return ADMIN_MAIN_PANEL_STATE

async def admin_command_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop('editing_pid', None)
    context.user_data.pop('new_pname', None)
    context.user_data.pop('admin_product_options_message_to_edit', None)
    context.user_data.pop('last_product_list_message_id', None)
    return await display_admin_panel(update,context, edit_message=False)

async def admin_panel_return_direct_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query: await query.answer()
    context.user_data.pop('editing_pid', None); context.user_data.pop('new_pname', None)
    context.user_data.pop('admin_product_options_message_to_edit', None)
    return_state = await display_admin_panel(update,context,True)
    return return_state

async def admin_add_prod_entry_cb(update:Update,context:ContextTypes.DEFAULT_TYPE)->int:
    q=update.callback_query;await q.answer();uid=q.from_user.id;await q.edit_message_text(await _(context,"admin_enter_product_name",user_id=uid));return ADMIN_ADD_PROD_NAME
async def admin_add_prod_name_state(update:Update,context:ContextTypes.DEFAULT_TYPE)->int:
    uid=update.effective_user.id;pname=update.message.text;context.user_data['new_pname']=pname;await update.message.reply_text(await _(context,"admin_enter_product_price",user_id=uid,product_name=pname));return ADMIN_ADD_PROD_PRICE
async def admin_add_prod_price_state(update:Update,context:ContextTypes.DEFAULT_TYPE)->int:
    user_id=update.effective_user.id; name=context.user_data.get('new_pname')
    try: price_str = update.message.text; price=float(price_str); assert price>0
    except (ValueError, AssertionError):
        await update.message.reply_text(await _(context,"admin_invalid_price",user_id=user_id))
        return ADMIN_ADD_PROD_PRICE
    if not name:
        await update.message.reply_text(await _(context,"generic_error_message",user_id=user_id, default="Error: Product name was lost. Please start over."))
        await display_admin_panel(update, context, edit_message=False)
        return ConversationHandler.END

    format_kwargs={'user_id':user_id,'product_name':name}
    msg_key="admin_product_added" if db_operations.add_product_to_db(name,price) else "admin_product_add_failed"
    if msg_key=="admin_product_added": format_kwargs['price']=f"{price:.2f}"
    await update.message.reply_text(await _(context,msg_key,**format_kwargs))
    context.user_data.pop('new_pname', None)
    await display_admin_panel(update, context, edit_message=False); return ConversationHandler.END

async def admin_manage_prod_list_entry_cb(update:Update,context:ContextTypes.DEFAULT_TYPE)->int:
    q=update.callback_query;await q.answer();uid=q.from_user.id
    context.user_data.pop('editing_pid',None)
    context.user_data.pop('admin_product_options_message_to_edit', None)

    prods=db_operations.get_products_from_db(False);kb,txt=[],""
    if not prods:
        txt=await _(context,"admin_no_products_to_manage",user_id=uid)
        kb.append([InlineKeyboardButton(await _(context,"admin_back_to_admin_panel_button",user_id=uid),callback_data="admin_panel_return_direct_cb")])
    else:
        txt=await _(context,"admin_select_product_to_manage",user_id=uid)
        for pid,name,price,avail in prods:
            stat_key="admin_status_available" if avail else "admin_status_unavailable"
            stat=await _(context,stat_key,user_id=uid,default="Available" if avail else "Unavailable")
            kb.append([InlineKeyboardButton(f"{name} - {price:.2f} EUR ({stat})",callback_data=f"admin_manage_select_prod_{pid}")])
        kb.append([InlineKeyboardButton(await _(context,"admin_back_to_admin_panel_button",user_id=uid),callback_data="admin_panel_return_direct_cb")])
    await q.edit_message_text(text=txt,reply_markup=InlineKeyboardMarkup(kb));return ADMIN_MANAGE_PROD_LIST

async def admin_manage_prod_selected_cb(update:Update,context:ContextTypes.DEFAULT_TYPE)->int:
    q = update.callback_query
    await q.answer()
    uid=q.from_user.id
    try:pid=int(q.data.split('_')[-1])
    except (IndexError, ValueError):
        await q.message.edit_text(await _(context,"generic_error_message",user_id=uid,default="Error parsing product ID."))
        return ADMIN_MANAGE_PROD_LIST
    prod=db_operations.get_product_by_id(pid)
    if not prod:
        await q.message.edit_text(await _(context,"product_not_found",user_id=uid,default="Product not found."))
        return ADMIN_MANAGE_PROD_LIST

    context.user_data['editing_pid']=pid
    pname,pprice,pavail=prod[1],prod[2],prod[3]
    avail_key="admin_set_unavailable_button" if pavail else "admin_set_available_button"
    kb=[
        [InlineKeyboardButton(await _(context,"admin_change_price_button",user_id=uid,price=f"{pprice:.2f}"),callback_data="admin_manage_edit_price_entry_cb")],
        [InlineKeyboardButton(await _(context,avail_key,user_id=uid),callback_data=f"admin_manage_toggle_avail_cb_{1-pavail}")],
        [InlineKeyboardButton(await _(context,"admin_delete_product_button",user_id=uid),callback_data="admin_manage_delete_confirm_cb")],
        [InlineKeyboardButton(await _(context,"admin_back_to_product_list_button",user_id=uid),callback_data="admin_manage_prod_list_refresh_cb")]
    ]
    await q.message.edit_text(await _(context,"admin_managing_product",user_id=uid,product_name=pname),reply_markup=InlineKeyboardMarkup(kb))
    return ADMIN_MANAGE_PROD_OPTIONS

async def admin_manage_edit_price_entry_cb(update:Update,context:ContextTypes.DEFAULT_TYPE)->int:
    q=update.callback_query;await q.answer();uid=q.from_user.id;edit_pid=context.user_data.get('editing_pid')
    if not edit_pid:
        await q.message.edit_text(await _(context,"generic_error_message",user_id=uid,default="Error: No product selected for price edit."))
        q.data = "admin_manage_prod_list_refresh_cb" # Callback data for list entry
        return await admin_manage_prod_list_entry_cb(update, context)

    prod=db_operations.get_product_by_id(edit_pid)
    if not prod:
        await q.message.edit_text(await _(context,"product_not_found",user_id=uid,default="Product not found for price edit."))
        q.data = "admin_manage_prod_list_refresh_cb"
        return await admin_manage_prod_list_entry_cb(update, context)

    context.user_data['admin_product_options_message_to_edit'] = q.message
    await q.message.edit_text(await _(context,"admin_enter_new_price",user_id=uid,product_name=prod[1],current_price=f"{prod[2]:.2f}"))
    return ADMIN_MANAGE_PROD_EDIT_PRICE

async def admin_manage_edit_price_state(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    new_price_str = update.message.text
    editing_pid = context.user_data.get('editing_pid')
    original_options_message: Message | None = context.user_data.pop('admin_product_options_message_to_edit', None)

    if not editing_pid:
        await update.message.reply_text(await _(context, "generic_error_message", user_id=user_id, default="Error: Product ID missing for price update. Session may have expired."))
        return await display_admin_panel(update, context, edit_message=False)

    try:
        new_price = float(new_price_str)
        assert new_price > 0
    except (ValueError, AssertionError):
        await update.message.reply_text(await _(context, "admin_invalid_price", user_id=user_id))
        if original_options_message: # Restore if validation fails for next attempt
             context.user_data['admin_product_options_message_to_edit'] = original_options_message
        return ADMIN_MANAGE_PROD_EDIT_PRICE

    success = db_operations.update_product_in_db(editing_pid, price=new_price)
    msg_key = "admin_price_updated" if success else "admin_price_update_failed"
    await update.message.reply_text(await _(context, msg_key, user_id=user_id, product_id=editing_pid))

    if not original_options_message:
        logger.error("Critical: 'admin_product_options_message_to_edit' not found. Cannot refresh menu.")
        await update.message.reply_text(await _(context, "admin_error_refreshing_menu", user_id=user_id))
        return await display_admin_panel(update, context, edit_message=False)

    class MockCallbackQueryForProductOptions:
        def __init__(self, effective_user_obj, message_to_act_on: Message, product_id_for_data: int):
            self.from_user = effective_user_obj
            self.message = message_to_act_on
            self.data = f"admin_manage_select_prod_{product_id_for_data}"
            self.id = "mock_callback_query_id"
        async def answer(self): pass

    mock_cb_query = MockCallbackQueryForProductOptions(
        update.effective_user, original_options_message, editing_pid
    )
    mock_update_obj = Update(update_id=update.update_id, callback_query=mock_cb_query)
    if not hasattr(mock_update_obj, 'effective_user') or not mock_update_obj.effective_user:
        mock_update_obj.effective_user = update.effective_user
    return await admin_manage_prod_selected_cb(mock_update_obj, context)

async def admin_manage_toggle_avail_cb(update:Update,context:ContextTypes.DEFAULT_TYPE)->int:
    q=update.callback_query;await q.answer();uid=q.from_user.id;edit_pid=context.user_data.get('editing_pid')
    if not edit_pid:
        await q.message.edit_text(await _(context,"generic_error_message",user_id=uid,default="Error: No product selected."))
        q.data = "admin_manage_prod_list_refresh_cb"
        return await admin_manage_prod_list_entry_cb(update, context)
    try:new_avail=int(q.data.split('_')[-1])
    except (IndexError, ValueError):
        await q.message.edit_text(await _(context,"generic_error_message",user_id=uid,default="Error parsing availability."))
        q.data=f"admin_manage_select_prod_{edit_pid}"
        return await admin_manage_prod_selected_cb(update,context)

    db_operations.update_product_in_db(edit_pid,is_available=new_avail)
    q.data=f"admin_manage_select_prod_{edit_pid}"
    return await admin_manage_prod_selected_cb(update,context)

async def admin_manage_delete_confirm_cb(update:Update,context:ContextTypes.DEFAULT_TYPE)->int:
    q=update.callback_query;await q.answer();uid=q.from_user.id;edit_pid=context.user_data.get('editing_pid')
    if not edit_pid:
        await q.message.edit_text(await _(context,"generic_error_message",user_id=uid,default="Error: No product selected."))
        q.data = "admin_manage_prod_list_refresh_cb"
        return await admin_manage_prod_list_entry_cb(update, context)
    prod=db_operations.get_product_by_id(edit_pid)
    if not prod:
        await q.message.edit_text(await _(context,"product_not_found",user_id=uid,default="Product not found."))
        q.data = "admin_manage_prod_list_refresh_cb"
        return await admin_manage_prod_list_entry_cb(update, context)
    kb=[[InlineKeyboardButton(await _(context,"admin_confirm_delete_yes_button",user_id=uid,product_name=prod[1]),callback_data="admin_manage_delete_do_cb")],[InlineKeyboardButton(await _(context,"admin_confirm_delete_no_button",user_id=uid),callback_data=f"admin_manage_select_prod_{edit_pid}")]]
    await q.message.edit_text(await _(context,"admin_confirm_delete_prompt",user_id=uid,product_name=prod[1]),reply_markup=InlineKeyboardMarkup(kb));return ADMIN_MANAGE_PROD_DELETE_CONFIRM

async def admin_manage_delete_do_cb(update:Update,context:ContextTypes.DEFAULT_TYPE)->int:
    q=update.callback_query;await q.answer();uid=q.from_user.id;edit_pid=context.user_data.get('editing_pid')
    if not edit_pid:
        await q.message.edit_text(await _(context,"generic_error_message",user_id=uid,default="Error: Product ID missing."))
        q.data = "admin_manage_prod_list_refresh_cb"
        return await admin_manage_prod_list_entry_cb(update, context)
    deleted = db_operations.delete_product_from_db(edit_pid)
    msg_key="admin_product_deleted" if deleted else "admin_product_delete_failed"
    await q.message.edit_text(await _(context,msg_key,user_id=uid,product_id=edit_pid))
    context.user_data.pop('editing_pid',None)
    q.data = "admin_manage_prod_list_entry_cb" # Pattern for list entry
    return await admin_manage_prod_list_entry_cb(update,context)

async def admin_clear_completed_orders_entry_cb(update:Update,context:ContextTypes.DEFAULT_TYPE)->int:
    q=update.callback_query;await q.answer();uid=q.from_user.id
    confirm_txt=await _(context,"admin_clear_orders_confirm_prompt",user_id=uid,default="Sure to delete COMPLETED orders?");yes_txt=await _(context,"admin_clear_orders_yes_button",user_id=uid,default="YES, Delete");no_txt=await _(context,"admin_clear_orders_no_button",user_id=uid,default="NO, Cancel")
    kb=[[InlineKeyboardButton(yes_txt,callback_data="admin_clear_orders_do_confirm")],[InlineKeyboardButton(no_txt,callback_data="admin_panel_return_direct_cb")]]
    await q.edit_message_text(text=confirm_txt,reply_markup=InlineKeyboardMarkup(kb));return ADMIN_CLEAR_ORDERS_CONFIRM

async def admin_clear_orders_do_confirm_cb(update:Update,context:ContextTypes.DEFAULT_TYPE)->int:
    q=update.callback_query;await q.answer();uid=q.from_user.id
    if not(ADMIN_IDS and uid in ADMIN_IDS):await q.edit_message_text(await _(context,"admin_unauthorized",user_id=uid));return ConversationHandler.END
    deleted_count=db_operations.delete_completed_orders_from_db()
    if deleted_count>0:msg=await _(context,"admin_orders_cleared_success",user_id=uid,count=deleted_count,default=f"{deleted_count} orders cleared.")
    elif deleted_count==0:msg=await _(context,"admin_orders_cleared_none",user_id=uid,default="No completed orders.")
    else:msg=await _(context,"admin_orders_cleared_error",user_id=uid,default="Error clearing.")
    await q.edit_message_text(text=msg)
    await display_admin_panel(update,context,True)
    return ConversationHandler.END

async def admin_view_orders_direct_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query;await q.answer();uid=q.from_user.id
    orders=db_operations.get_all_orders_from_db()
    text_parts = [await _(context,"admin_all_orders_title",user_id=uid, default="📦 All Customer Orders:\n\n")]
    if not orders:
        text_parts.append(await _(context,"admin_no_orders_found",user_id=uid))
    else:
        for oid, cust_id_db, uname, date_val, total_val_float, status_val, items_val in orders:
            items_display = items_val.replace(chr(10), "\n  ") if items_val else "N/A"
            order_entry = await _(context,"admin_order_details_format",user_id=uid,order_id=oid,user_name=uname or "N/A",customer_id=cust_id_db,date=date_val,total=total_val_float,status=status_val.capitalize(),items=items_display, default="Order...") # Pass float
            text_parts.append(order_entry)
    full_text = "".join(text_parts)
    kb=[[InlineKeyboardButton(await _(context,"admin_back_to_admin_panel_button",user_id=uid),callback_data="admin_panel_return_direct_cb")]]
    reply_markup = InlineKeyboardMarkup(kb)
    try:
        if len(full_text) > 4096: await q.edit_message_text(text=full_text[:4000]+"...\n(Truncated)", reply_markup=reply_markup)
        else: await q.edit_message_text(text=full_text,reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error admin_view_orders: {e}")
        error_msg = await _(context, "generic_error_message", user_id=uid, default="Error displaying orders.")
        try: await q.edit_message_text(text=error_msg, reply_markup=reply_markup)
        except:
            if q.message: await q.message.reply_text(error_msg)
            elif uid: await context.bot.send_message(chat_id=uid, text=error_msg)

async def admin_shop_list_direct_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query;await q.answer();uid=q.from_user.id
    slist=db_operations.get_shopping_list_from_db()
    text=await _(context,"admin_shopping_list_title",user_id=uid, default="Shopping List:")+"\n\n" if slist else await _(context,"admin_shopping_list_empty",user_id=uid)
    if slist:
        for name,qty in slist: text+=await _(context,"admin_shopping_list_item_format",user_id=uid,name=name,total_quantity=f"{qty:.2f}", default=f"- {name}:{qty}kg\n")
    kb=[[InlineKeyboardButton(await _(context,"admin_back_to_admin_panel_button",user_id=uid),callback_data="admin_panel_return_direct_cb")]]
    reply_markup = InlineKeyboardMarkup(kb)
    try: await q.edit_message_text(text=text,reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error admin_shop_list: {e}")
        error_msg = await _(context, "generic_error_message", user_id=uid, default="Error displaying shopping list.")
        try: await q.edit_message_text(text=error_msg, reply_markup=reply_markup)
        except:
            if q.message: await q.message.reply_text(error_msg)
            elif uid: await context.bot.send_message(chat_id=uid, text=error_msg)

# --- GENERAL CANCEL HANDLER ---
async def general_cancel_command_handler(update:Update,context:ContextTypes.DEFAULT_TYPE)->int:
    uid = update.effective_user.id if update.effective_user else None
    cancel_txt = await _(context, "action_cancelled", user_id=uid, default="Action cancelled.")
    message_sent_or_edited = False
    try:
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.edit_text(cancel_txt)
            message_sent_or_edited = True
        elif update.message:
            await update.message.reply_text(cancel_txt, reply_markup=ReplyKeyboardRemove())
            message_sent_or_edited = True
    except Exception as e: logger.warning(f"Cancel handler error on edit/reply: {e}")
    if not message_sent_or_edited and update.effective_chat:
        try: await context.bot.send_message(chat_id=update.effective_chat.id, text=cancel_txt, reply_markup=ReplyKeyboardRemove())
        except Exception as e: logger.error(f"Fallback cancel send error: {e}")

    lang_code = context.user_data.get('language_code')
    cart_data = context.user_data.get('cart')
    keys_to_pop=['current_product_id','current_product_name','current_product_price','new_pname','editing_pid', 'admin_product_options_message_to_edit', 'last_product_list_message_id']
    for k_pop in keys_to_pop: context.user_data.pop(k_pop, None)
    if lang_code: context.user_data['language_code'] = lang_code
    if cart_data is not None: context.user_data['cart'] = cart_data

    if ADMIN_IDS and uid in ADMIN_IDS:
        await display_admin_panel(update, context, edit_message=bool(update.callback_query))
    else:
        await display_main_menu(update, context, edit_message=bool(update.callback_query))
    return ConversationHandler.END

# --- CONVERSATION HANDLER DEFINITIONS ---
general_conv_fallbacks = [
    CallbackQueryHandler(back_to_main_menu_cb_handler, pattern="^main_menu_direct_cb_ender$"),
    CommandHandler("cancel", general_cancel_command_handler),
    CommandHandler("start", start_command_handler)
]
admin_conv_fallbacks = [
    CallbackQueryHandler(admin_panel_return_direct_cb, pattern="^admin_panel_return_direct_cb$"),
    CommandHandler("cancel", general_cancel_command_handler),
    CommandHandler("admin", admin_command_entry)
]

lang_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(select_language_entry, pattern="^select_language_entry$")],
    states={SELECT_LANGUAGE_STATE: [CallbackQueryHandler(language_selected_state, pattern="^lang_select_(en|lt)$")]},
    fallbacks=general_conv_fallbacks
)

order_conv = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(order_flow_browse_entry, pattern="^order_flow_browse_entry$"),
        CallbackQueryHandler(order_flow_manage_cart_cb, pattern="^order_flow_view_cart_direct_entry$") # View cart button from main menu
    ],
    states={
        ORDER_FLOW_BROWSING_PRODUCTS: [ # Combined cart & product view
            CallbackQueryHandler(order_flow_product_selected, pattern="^order_flow_select_prod_\d+$"),
            CallbackQueryHandler(order_flow_manage_cart_cb, pattern="^order_flow_manage_cart_cb$"), # "Manage Cart" button
            CallbackQueryHandler(order_flow_checkout_cb, pattern="^order_flow_checkout_cb$"),
            # This callback is for "Back to Products & Cart View" from detailed cart
            CallbackQueryHandler(lambda u,c: display_cart_and_products(u, c, u.callback_query.from_user.id, edit_message_id=u.callback_query.message.message_id), pattern="^order_flow_browse_return_cb_detailed$"),
        ],
        ORDER_FLOW_SELECTING_QUANTITY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, order_flow_quantity_typed)
        ],
        ORDER_FLOW_VIEWING_CART: [ # Detailed cart management (remove items, checkout)
            CallbackQueryHandler(order_flow_remove_item_cb, pattern="^order_flow_remove_item_\d+$"),
            CallbackQueryHandler(order_flow_checkout_cb, pattern="^order_flow_checkout_cb$"),
             # This callback is for "Back to Products & Cart View" from detailed cart
            CallbackQueryHandler(lambda u,c: display_cart_and_products(u, c, u.callback_query.from_user.id, edit_message_id=u.callback_query.message.message_id), pattern="^order_flow_browse_return_cb_detailed$"),
        ]
    },
    fallbacks=general_conv_fallbacks
)

admin_add_prod_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(admin_add_prod_entry_cb, pattern="^admin_add_prod_entry_cb$")],
    states={
        ADMIN_ADD_PROD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_prod_name_state)],
        ADMIN_ADD_PROD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_prod_price_state)],
    },
    fallbacks=admin_conv_fallbacks
)

admin_manage_prod_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(admin_manage_prod_list_entry_cb, pattern="^admin_manage_prod_list_entry_cb$")],
    states={
        ADMIN_MANAGE_PROD_LIST: [
            CallbackQueryHandler(admin_manage_prod_selected_cb, pattern="^admin_manage_select_prod_\d+$")
        ],
        ADMIN_MANAGE_PROD_OPTIONS: [
            CallbackQueryHandler(admin_manage_edit_price_entry_cb, pattern="^admin_manage_edit_price_entry_cb$"),
            CallbackQueryHandler(admin_manage_toggle_avail_cb, pattern="^admin_manage_toggle_avail_cb_(0|1)$"),
            CallbackQueryHandler(admin_manage_delete_confirm_cb, pattern="^admin_manage_delete_confirm_cb$"),
            CallbackQueryHandler(admin_manage_prod_list_entry_cb, pattern="^admin_manage_prod_list_refresh_cb$")
        ],
        ADMIN_MANAGE_PROD_EDIT_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_manage_edit_price_state)],
        ADMIN_MANAGE_PROD_DELETE_CONFIRM: [
            CallbackQueryHandler(admin_manage_delete_do_cb, pattern="^admin_manage_delete_do_cb$"),
            CallbackQueryHandler(admin_manage_prod_selected_cb, pattern="^admin_manage_select_prod_\d+$") # Back from confirm no
        ]
    },
    fallbacks=admin_conv_fallbacks
)

admin_clear_orders_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(admin_clear_completed_orders_entry_cb, pattern="^admin_clear_orders_entry_cb$")],
    states={
        ADMIN_CLEAR_ORDERS_CONFIRM: [
            CallbackQueryHandler(admin_clear_orders_do_confirm_cb, pattern="^admin_clear_orders_do_confirm$")
        ]
    },
    fallbacks=admin_conv_fallbacks
)
