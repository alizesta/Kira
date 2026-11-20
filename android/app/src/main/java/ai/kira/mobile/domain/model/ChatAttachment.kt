package ai.kira.mobile.domain.model

data class ChatAttachmentInput(val name:String,val mimeType:String,val bytes:ByteArray)
data class ChatAttachmentInfo(val id:String,val name:String,val mimeType:String,val sizeBytes:Long)
