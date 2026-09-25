import { WEBUI_API_BASE_URL } from '$lib/constants';

export const manageMemory = async (token: string, chatId: string, action: string, payload: object = {}) => {
	const response = await fetch(`${WEBUI_API_BASE_URL}/chat-memory/manage`, {
		method: 'POST',
		headers: { Accept: 'application/json', 'Content-Type': 'application/json', authorization: `Bearer ${token}` },
		body: JSON.stringify({ chat_id: chatId, action, payload })
	});
	if (!response.ok) throw await response.json();
	return response.json();
};
