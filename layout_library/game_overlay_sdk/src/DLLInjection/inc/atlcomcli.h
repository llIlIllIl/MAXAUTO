#pragma once

template <class T>
class CComPtr
{
public:
    CComPtr () noexcept : ptr_ (nullptr)
    {
    }

    explicit CComPtr (T *ptr) noexcept : ptr_ (ptr)
    {
        InternalAddRef ();
    }

    CComPtr (const CComPtr &other) noexcept : ptr_ (other.ptr_)
    {
        InternalAddRef ();
    }

    CComPtr &operator= (const CComPtr &other) noexcept
    {
        if (this != &other)
        {
            CComPtr copy (other);
            Swap (copy);
        }
        return *this;
    }

    ~CComPtr ()
    {
        InternalRelease ();
    }

    T *operator-> () const noexcept
    {
        return ptr_;
    }

    operator T * () const noexcept
    {
        return ptr_;
    }

    T **operator& () noexcept
    {
        InternalRelease ();
        return &ptr_;
    }

    T *Get () const noexcept
    {
        return ptr_;
    }

    T **GetAddressOf () noexcept
    {
        return &ptr_;
    }

    void Attach (T *ptr) noexcept
    {
        InternalRelease ();
        ptr_ = ptr;
    }

    T *Detach () noexcept
    {
        T *ptr = ptr_;
        ptr_ = nullptr;
        return ptr;
    }

    void Release () noexcept
    {
        InternalRelease ();
    }

private:
    void Swap (CComPtr &other) noexcept
    {
        T *tmp = ptr_;
        ptr_ = other.ptr_;
        other.ptr_ = tmp;
    }

    void InternalAddRef () noexcept
    {
        if (ptr_ != nullptr)
        {
            ptr_->AddRef ();
        }
    }

    void InternalRelease () noexcept
    {
        T *ptr = ptr_;
        if (ptr != nullptr)
        {
            ptr_ = nullptr;
            ptr->Release ();
        }
    }

    T *ptr_;
};
