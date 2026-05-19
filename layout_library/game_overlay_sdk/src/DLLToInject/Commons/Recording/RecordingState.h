//
// Copyright(c) 2016 Advanced Micro Devices, Inc. All rights reserved.
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files(the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and / or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions :
//
// The above copyright notice and this permission notice shall be included in all
// copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.
//

#pragma once

#include <chrono>
#include <cstdint>
#include <string>

#include "Utility/OverlayFrameIPC.h"

enum class TextureState
{
    Default,
    Start,
    Stop
};

class RecordingState final
{
public:
    static RecordingState &GetInstance ();
    RecordingState (RecordingState const &) = delete;
    void operator= (RecordingState const &) = delete;

    bool Started ();
    bool Stopped ();
    bool IsOverlayShowing ();
    void Start ();
    void Stop ();

    TextureState Update ();
    void SetDisplayTimes (float start, float end);
    void SetRecordingTime (float time);
    void HideOverlay ();
    void ShowOverlay ();

    char *GetOverlayMessage ();
    void SetOverlayMessage (char *message);
    void SetOverlayFrame (
        const GameOverlayIPC::OverlayFrameHeader &header, const unsigned char *rgbaData);
    bool HasOverlayFrame () const;
    bool IsOverlayFrameVisible () const;
    int GetOverlayFrameWidth () const;
    int GetOverlayFrameHeight () const;
    int GetOverlayFrameStride () const;
    std::uint32_t GetOverlayFrameSeq () const;
    const unsigned char *GetOverlayFrameData () const;

private:
    RecordingState ();

    bool recording_ = false;
    bool stateChanged_ = false;
    bool showOverlay_ = false;
    float startDisplayTime_ = 1.0f;
    float endDisplayTime_ = 1.0f;
    float recordingTime_ = 0.0f;

    volatile char overlayMessage_[2048];
    bool overlayFrameAvailable_ = false;
    bool overlayFrameVisible_ = false;
    int overlayFrameWidth_ = 0;
    int overlayFrameHeight_ = 0;
    int overlayFrameStride_ = 0;
    std::uint32_t overlayFrameSeq_ = 0;
    unsigned char overlayFrameData_[GameOverlayIPC::OverlayFrameMaxBytes] = {};

    TextureState currentTextureState_ = TextureState::Default;
    std::chrono::high_resolution_clock::time_point currentStateStart_;
};
